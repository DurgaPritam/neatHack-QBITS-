"""Tools the LLM may call during claim verification.

All arguments come from the LLM, which has read untrusted repo text, so every
argument is validated: paths must name something in this repo's tree, URLs go
through the M1 link checker's SSRF guard. All output is wrapped as UNTRUSTED DATA.
"""
import json
import posixpath
import re

from app.agent.prompts import untrusted
from app.steps import StepLog
from app.tools.github import GitHubClient, GitHubError, RepoRef
from app.tools.links import check_links
from app.tools.search import RepoSnapshot, format_matches
from app.tracing import span

MAX_FILES_READ = 10
READ_FILE_CHARS = 3000
MAX_PATTERN_LEN = 200
MAX_LIST_ENTRIES = 80
MAX_URL_LEN = 2000


class ToolArgError(ValueError):
    kind = "invalid_tool_args"


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_repo",
        "description": "PREFERRED. Search every text file in the repo (case-insensitive, literal; "
                       "separate alternatives with '|', e.g. 'import neatlogs|neatlogs.init'). "
                       "Returns matching lines as path:line with surrounding lines. Code first, README last.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "terms separated by |"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files and folders under a directory of the audited repo ('' for root).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "repo-relative directory, '' for root"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": f"Read {READ_FILE_CHARS} chars of a repo file with line numbers, from start_line "
                       f"(default 1). At most {MAX_FILES_READ} distinct files per audit; use search_repo first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "repo-relative file path"},
            "start_line": {"type": "integer", "minimum": 1}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "get_commits",
        "description": "Most recent commits: short sha, ISO date, first line of message.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["limit"]}}},
    {"type": "function", "function": {
        "name": "check_link",
        "description": "Check whether an http(s) URL is reachable; returns status code.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
]


def safe_repo_path(path, tree_paths: set[str], *, is_dir: bool = False) -> str:
    """Normalise an LLM-supplied path and make sure it stays inside the repo."""
    if not isinstance(path, str):
        raise ToolArgError("path must be a string")
    p = path.strip()
    if "\x00" in p or "\\" in p or re.match(r"^[a-z]+://", p, re.I):
        raise ToolArgError(f"invalid path: {path!r}")
    if p.startswith("/") or p.startswith("~"):
        raise ToolArgError(f"absolute paths are not allowed: {path!r}")
    if ".." in p.split("/"):
        raise ToolArgError(f"path escapes the repo: {path!r}")
    p = posixpath.normpath(p) if p else ""
    if p == ".":
        p = ""
    if is_dir:
        if p and not any(t.startswith(p + "/") for t in tree_paths):
            raise ToolArgError(f"no such directory in repo: {p!r}")
    elif p not in tree_paths:
        raise ToolArgError(f"no such file in repo: {p!r}")
    return p


def safe_url(url) -> str:
    if not isinstance(url, str) or len(url) > MAX_URL_LEN:
        raise ToolArgError("url must be a string under 2000 chars")
    u = url.strip()
    if not re.match(r"^https?://[^\s/]+", u, re.I):
        raise ToolArgError(f"only http(s) URLs are allowed: {url!r}")
    return u


class RepoToolbox:
    def __init__(self, gh: GitHubClient | None, ref: RepoRef | None, branch: str,
                 tree_paths: list[str], commits: list[dict] | None, steps: StepLog,
                 snapshot: RepoSnapshot | None = None):
        self.gh, self.ref, self.branch = gh, ref, branch
        self.snapshot = snapshot
        self.tree = set(tree_paths) | set(snapshot.files if snapshot else ())
        self.searched_paths: set[str] = set()  # paths whose lines the agent saw via search
        self.commits = commits or []
        self.steps = steps
        self.files_read: dict[str, str] = {}
        self.checked_urls: set[str] = set()
        self.calls = 0

    async def dispatch(self, name: str, raw_args: str | None) -> str:
        """Run one tool call. Never raises: errors go back to the LLM as text and into the step log."""
        self.calls += 1
        with self.steps.step(f"tool.{name}") as s:
            try:
                args = json.loads(raw_args or "{}")
                if not isinstance(args, dict):
                    raise ToolArgError("arguments must be a JSON object")
            except json.JSONDecodeError as exc:
                raise ToolArgError(f"arguments are not valid JSON: {exc}") from exc
            s.data["args"] = {k: str(v)[:200] for k, v in args.items()}
            fn = {"search_repo": self.search_repo, "list_files": self.list_files,
                  "read_file": self.read_file, "get_commits": self.get_commits,
                  "check_link": self.check_link}.get(name)
            if fn is None:
                raise ToolArgError(f"unknown tool {name!r}")
            allowed = ("path", "limit", "url", "pattern", "start_line")
            out = await fn(**{k: v for k, v in args.items() if k in allowed})
            s.detail = f"{len(out)} chars"
            return out
        # reached only if the step recorded a failure
        failed = self.steps.steps[-1]
        return f"ERROR ({failed.error_kind}): {failed.detail}"

    @span("TOOL", "agent.list_files")
    async def list_files(self, path: str = "") -> str:
        p = safe_repo_path(path, self.tree, is_dir=True)
        prefix = p + "/" if p else ""
        entries = set()
        for t in self.tree:
            if t.startswith(prefix):
                head, _, rest = t[len(prefix):].partition("/")
                entries.add(head + ("/" if rest else ""))
        listing = sorted(entries)
        more = f"\n... {len(listing) - MAX_LIST_ENTRIES} more" if len(listing) > MAX_LIST_ENTRIES else ""
        return untrusted(f"list_files:{p or '/'}", "\n".join(listing[:MAX_LIST_ENTRIES]) + more)

    @span("TOOL", "agent.search_repo")
    async def search_repo(self, pattern: str) -> str:
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > MAX_PATTERN_LEN:
            raise ToolArgError(f"pattern must be a non-empty string under {MAX_PATTERN_LEN} chars")
        if self.snapshot is None:
            raise ToolArgError("repo copy unavailable (tarball download failed); use read_file")
        try:
            matches, total, hit_files = self.snapshot.search(pattern)
        except ValueError as exc:
            raise ToolArgError(str(exc)) from exc
        self.searched_paths.update(m["path"] for m in matches)
        return untrusted(f"search:{pattern[:60]}", format_matches(pattern, matches, total, hit_files))

    @span("TOOL", "agent.read_file")
    async def read_file(self, path: str, start_line: int = 1) -> str:
        p = safe_repo_path(path, self.tree)
        try:
            start = max(1, int(start_line))
        except (TypeError, ValueError) as exc:
            raise ToolArgError("start_line must be an integer") from exc
        if p not in self.files_read:
            if len(self.files_read) >= MAX_FILES_READ:
                raise ToolArgError(f"file budget used up ({MAX_FILES_READ} files); use search_repo")
            self.files_read[p] = await self._load(p)
        text = self.files_read[p]
        lines = text.splitlines()
        numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines[start - 1:], start))
        if len(numbered) > READ_FILE_CHARS:
            numbered = numbered[:READ_FILE_CHARS] + f"\n[truncated; file has {len(lines)} lines]"
        return untrusted(f"file:{p}", numbered or f"(no lines from {start}; file has {len(lines)} lines)")

    async def _load(self, path: str) -> str:
        if self.snapshot is not None and path in self.snapshot.files:
            return self.snapshot.files[path]
        if self.gh is None or self.ref is None:
            raise ToolArgError("repo contents unavailable")
        try:
            return await self.gh.get_file(self.ref, path, self.branch)
        except GitHubError as exc:
            raise ToolArgError(f"could not read {path}: {exc.kind}") from exc

    @span("TOOL", "agent.get_commits")
    async def get_commits(self, limit: int = 20) -> str:
        try:
            n = max(1, min(int(limit), 50))
        except (TypeError, ValueError) as exc:
            raise ToolArgError("limit must be an integer") from exc
        lines = [f"{c['sha']} {c['committed_at']} {c['message']}" for c in self.commits[:n]]
        return untrusted("commits", "\n".join(lines) or "(no commits available)")

    @span("TOOL", "agent.check_link")
    async def check_link(self, url: str) -> str:
        u = safe_url(url)
        [r] = await check_links([u])  # SSRF guard lives in the link checker
        self.checked_urls.update({u, r["final_url"]})
        return json.dumps({k: r[k] for k in ("url", "status", "ok", "error", "final_url")})

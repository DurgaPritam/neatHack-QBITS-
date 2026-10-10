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
from app.tracing import span

MAX_FILES_READ = 10
READ_FILE_CHARS = 4000
MAX_LIST_ENTRIES = 80
MAX_URL_LEN = 2000


class ToolArgError(ValueError):
    kind = "invalid_tool_args"


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files and folders under a directory of the audited repo ('' for root).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "repo-relative directory, '' for root"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": f"Read a repo file (first {READ_FILE_CHARS} chars, with line numbers). "
                       f"At most {MAX_FILES_READ} distinct files per audit.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "repo-relative file path from list_files"}},
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
                 tree_paths: list[str], commits: list[dict] | None, steps: StepLog):
        self.gh, self.ref, self.branch = gh, ref, branch
        self.tree = set(tree_paths)
        self.commits = commits or []
        self.steps = steps
        self.files_read: dict[str, str] = {}
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
            fn = {"list_files": self.list_files, "read_file": self.read_file,
                  "get_commits": self.get_commits, "check_link": self.check_link}.get(name)
            if fn is None:
                raise ToolArgError(f"unknown tool {name!r}")
            out = await fn(**{k: v for k, v in args.items() if k in ("path", "limit", "url")})
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

    @span("TOOL", "agent.read_file")
    async def read_file(self, path: str) -> str:
        p = safe_repo_path(path, self.tree)
        if p not in self.files_read:
            if len(self.files_read) >= MAX_FILES_READ:
                raise ToolArgError(f"file budget used up ({MAX_FILES_READ} files); decide with what you have")
            if self.gh is None or self.ref is None:
                raise ToolArgError("repo contents unavailable")
            try:
                text = await self.gh.get_file(self.ref, p, self.branch)
            except GitHubError as exc:
                raise ToolArgError(f"could not read {p}: {exc.kind}") from exc
            numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(text.splitlines(), 1))
            if len(numbered) > READ_FILE_CHARS:
                numbered = numbered[:READ_FILE_CHARS] + f"\n[truncated; file is {len(text)} chars]"
            self.files_read[p] = numbered
        return untrusted(f"file:{p}", self.files_read[p])

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
        return json.dumps({k: r[k] for k in ("url", "status", "ok", "error", "final_url")})

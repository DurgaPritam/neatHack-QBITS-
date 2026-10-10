"""Read-only GitHub access: repo metadata, README, file tree, file contents, commits.

Never clones, never executes. Everything returned is UNTRUSTED repo data.
Failures raise GitHubError with a machine-readable `kind` so callers can record
them as steps instead of crashing.
"""
import asyncio
import base64
import re
from dataclasses import dataclass

import httpx

from app import config
from app.tracing import span

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_FILE_BYTES = 200_000
MAX_COMMIT_PAGES = 3  # 300 commits is plenty to judge the hackathon window

_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?(?:[#?].*)?$"
)
_SHORT_RE = re.compile(r"^([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)$")


class GitHubError(Exception):
    """kind: invalid_url | not_found | private | rate_limited | forbidden | network | http_error"""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_repo_url(url: str) -> RepoRef:
    url = url.strip()
    m = _URL_RE.match(url) or _SHORT_RE.match(url)
    if not m:
        raise GitHubError("invalid_url", f"not a GitHub repo URL: {url!r}")
    return RepoRef(m.group(1), m.group(2))


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        token = config.GITHUB_TOKEN if token is None else token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "prejudge-auditor",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self._http = httpx.AsyncClient(
            headers=headers, timeout=timeout or config.HTTP_TIMEOUT, follow_redirects=True,
            transport=transport,  # injectable for tests
        )
        self.rate_limit_remaining: int | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    async def _get(self, url: str, params: dict | None = None, retries: int = 2) -> httpx.Response:
        for attempt in range(retries + 1):
            try:
                r = await self._http.get(url, params=params)
            except httpx.TimeoutException as exc:
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GitHubError("network", f"timeout fetching {url}") from exc
            except httpx.HTTPError as exc:
                raise GitHubError("network", f"{type(exc).__name__} fetching {url}") from exc

            remaining = r.headers.get("x-ratelimit-remaining")
            if remaining is not None:
                self.rate_limit_remaining = int(remaining)

            if r.status_code < 400:
                return r
            if r.status_code == 404:
                raise GitHubError("not_found", f"404 for {url}", 404)
            if r.status_code in (403, 429) and (remaining == "0" or "rate limit" in r.text.lower()):
                # Short secondary-limit waits are worth retrying; primary-limit resets are not.
                wait = int(r.headers.get("retry-after", "0") or 0)
                if 0 < wait <= 10 and attempt < retries:
                    await asyncio.sleep(wait)
                    continue
                hint = "" if self.authenticated else " (set GITHUB_TOKEN for 5000 req/h)"
                raise GitHubError("rate_limited", f"GitHub rate limit hit{hint}", r.status_code)
            if r.status_code == 403:
                raise GitHubError("forbidden", f"403 for {url}", 403)
            if r.status_code >= 500 and attempt < retries:
                await asyncio.sleep(2**attempt)
                continue
            raise GitHubError("http_error", f"HTTP {r.status_code} for {url}", r.status_code)
        raise GitHubError("network", f"gave up on {url}")  # unreachable in practice

    @span("TOOL", "github.get_repo")
    async def get_repo(self, ref: RepoRef) -> dict:
        """Repo metadata. Private repos look like 404 to an outsider, so 404 is reported as
        'not_found' with a hint; a visible-but-private repo is reported as 'private'."""
        try:
            data = (await self._get(f"{API}/repos/{ref.full_name}")).json()
        except GitHubError as exc:
            if exc.kind == "not_found":
                raise GitHubError(
                    "not_found", f"{ref.full_name} not found (missing, renamed, or private)", 404
                ) from exc
            raise
        if data.get("private"):
            raise GitHubError("private", f"{ref.full_name} is private; judges can't see it")
        return {
            "full_name": data["full_name"],
            "private": data.get("private", False),
            "default_branch": data.get("default_branch", "main"),
            "description": data.get("description"),
            "homepage": data.get("homepage"),
            "created_at": data.get("created_at"),
            "pushed_at": data.get("pushed_at"),
            "stars": data.get("stargazers_count", 0),
            "fork": data.get("fork", False),
            "archived": data.get("archived", False),
        }

    @span("TOOL", "github.get_readme")
    async def get_readme(self, ref: RepoRef) -> dict:
        data = (await self._get(f"{API}/repos/{ref.full_name}/readme")).json()
        text = _decode(data)
        return {"path": data.get("path"), "size": data.get("size"), "text": text}

    @span("TOOL", "github.get_tree")
    async def get_tree(self, ref: RepoRef, branch: str) -> dict:
        data = (
            await self._get(
                f"{API}/repos/{ref.full_name}/git/trees/{branch}", params={"recursive": "1"}
            )
        ).json()
        files = [
            {"path": e["path"], "size": e.get("size", 0)}
            for e in data.get("tree", [])
            if e.get("type") == "blob"
        ]
        return {"sha": data.get("sha"), "truncated": data.get("truncated", False), "files": files}

    @span("TOOL", "github.get_file")
    async def get_file(self, ref: RepoRef, path: str, branch: str) -> str:
        """File contents via raw.githubusercontent.com (doesn't count against the API limit)."""
        url = f"{RAW}/{ref.full_name}/{branch}/{path}"
        try:
            r = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise GitHubError("network", f"{type(exc).__name__} fetching {path}") from exc
        if r.status_code == 404:
            raise GitHubError("not_found", f"{path} not found", 404)
        if r.status_code >= 400:
            raise GitHubError("http_error", f"HTTP {r.status_code} for {path}", r.status_code)
        return r.content[:MAX_FILE_BYTES].decode("utf-8", errors="replace")

    @span("TOOL", "github.get_commits")
    async def get_commits(self, ref: RepoRef, branch: str) -> dict:
        commits: list[dict] = []
        truncated = False
        for page in range(1, MAX_COMMIT_PAGES + 1):
            r = await self._get(
                f"{API}/repos/{ref.full_name}/commits",
                params={"sha": branch, "per_page": 100, "page": page},
            )
            batch = r.json()
            for c in batch:
                info = c.get("commit", {})
                commits.append(
                    {
                        "sha": c.get("sha", "")[:12],
                        "message": (info.get("message") or "").splitlines()[0][:200]
                        if info.get("message")
                        else "",
                        "author": (info.get("author") or {}).get("name"),
                        "authored_at": (info.get("author") or {}).get("date"),
                        "committed_at": (info.get("committer") or {}).get("date"),
                    }
                )
            if len(batch) < 100:
                break
            if page == MAX_COMMIT_PAGES:
                truncated = 'rel="next"' in r.headers.get("link", "")
        return {"count": len(commits), "truncated": truncated, "commits": commits}


def _decode(content_payload: dict) -> str:
    raw = content_payload.get("content", "")
    if content_payload.get("encoding") == "base64":
        return base64.b64decode(raw)[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    return raw[:MAX_FILE_BYTES]

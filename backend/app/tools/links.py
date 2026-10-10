"""Extract links from README text, classify them, and check their HTTP status.

Links come from UNTRUSTED repo content, so every hop is checked against an
SSRF guard (no private, loopback, link-local or metadata addresses).
"""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app import config
from app.tracing import span

MAX_LINKS = 40
MAX_REDIRECTS = 5
CONCURRENCY = 8

_MD_LINK = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_HTML_LINK = re.compile(r"""(?:href|src)=["'](https?://[^"']+)["']""", re.I)
_BARE = re.compile(r"(?<![(\"'=])\bhttps?://[^\s<>()\"'`\]]+")

# Ordered: first match wins.
_KINDS: list[tuple[str, re.Pattern]] = [
    ("neatlogs_trace", re.compile(r"(^|\.)neatlogs\.com$")),
    ("entire", re.compile(r"(^|\.)entire\.(io|dev|com|ai)$")),
    ("cfo_ai", re.compile(r"(^|\.)cfo\.ai$")),
    ("video", re.compile(r"(^|\.)(youtube\.com|youtu\.be|loom\.com|vimeo\.com)$")),
    ("social", re.compile(r"(^|\.)(x\.com|twitter\.com|linkedin\.com|bsky\.app|threads\.net|dev\.to|medium\.com|hashnode\.dev)$")),
    ("github", re.compile(r"(^|\.)github\.com$")),
]

# Many sites (Cloudflare, X, LinkedIn) refuse bots; these codes don't mean the link is dead.
_BOT_BLOCK_CODES = {401, 403, 429, 999}


def extract_links(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for rx in (_MD_LINK, _HTML_LINK, _BARE):
        for m in rx.finditer(text or ""):
            url = m.group(1) if rx.groups else m.group(0)
            url = url.rstrip(".,;:!*_")
            seen.setdefault(url, None)
    return list(seen)[:MAX_LINKS]


def classify(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for kind, rx in _KINDS:
        if rx.search(host):
            return kind
    return "other"


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


async def _check_one(http: httpx.AsyncClient, url: str) -> dict:
    result = {"url": url, "kind": classify(url), "status": None, "ok": False,
              "final_url": url, "error": None}
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                result["error"] = "unsupported_url"
                return result
            if not await asyncio.to_thread(_is_public_host, parsed.hostname):
                result["error"] = "blocked_or_unresolvable_host"
                return result
            r = await http.head(current)
            if r.status_code in (403, 405, 501) or r.status_code >= 500:
                r = await http.get(current)  # some servers reject HEAD
            if r.is_redirect and "location" in r.headers:
                current = urljoin(current, r.headers["location"])
                continue
            result["status"] = r.status_code
            result["final_url"] = current
            result["ok"] = r.status_code < 400
            if r.status_code in _BOT_BLOCK_CODES:
                result["ok"] = None  # unknown: site blocks bots
                result["error"] = "bot_blocked"
            return result
        result["error"] = "too_many_redirects"
    except httpx.TimeoutException:
        result["error"] = "timeout"
    except httpx.HTTPError as exc:
        result["error"] = type(exc).__name__
    return result


@span("TOOL", "links.check_links")
async def check_links(urls: list[str]) -> list[dict]:
    """Check each URL; never raises. ok=True live, False dead, None unknown."""
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=False,  # we follow manually so each hop passes the SSRF guard
        headers={"User-Agent": "Mozilla/5.0 (prejudge link checker)"},
    ) as http:

        async def guarded(u: str) -> dict:
            async with sem:
                return await _check_one(http, u)

        return await asyncio.gather(*(guarded(u) for u in urls[:MAX_LINKS]))

"""Demo video duration from metadata only (never downloads media).

Order: YouTube Data API v3 (videos?part=contentDetails, needs YOUTUBE_API_KEY) for YouTube
links, then yt-dlp metadata, then "unknown". YouTube often blocks yt-dlp from cloud servers
("Sign in to confirm you're not a bot"), which is why the API comes first.

Only called for links already classified as video hosts (YouTube/Loom/Vimeo) whose host passed
the link checker's SSRF guard. If the duration can't be read we say "unknown"; we never guess.

Raw tool errors never reach users: each failure becomes a `reason_code` plus a friendly
`reason`. The raw text only goes to the neatlogs trace (secrets masked) and the server log.
"""
import asyncio
import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx

from app import config
from app.tracing import event, span

log = logging.getLogger(__name__)

MAX_DEMO_SECONDS = 180
TIMEOUT_S = 20
VIDEO_HOSTS = ("youtube.com", "youtu.be", "loom.com", "vimeo.com")
YT_API = "https://www.googleapis.com/youtube/v3/videos"
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# reason_code -> what users see. "Gone" codes mean judges can't watch the video either.
FRIENDLY = {
    "bot_check": "YouTube didn't let us read the video length automatically.",
    "private": "The video is private, so judges can't watch it.",
    "not_found": "We couldn't find a public video at this link (it may be private or removed).",
    "unavailable": "The video isn't available (it may have been removed or blocked).",
    "sign_in": "The video needs a sign-in (for example, it's age-restricted), so judges may not be able to watch it.",
    "timeout": "The video site took too long to answer, so we couldn't read the length.",
    "no_duration": "The video page doesn't list a length (live streams and premieres look like this).",
    "unsupported_host": "We only read lengths from YouTube, Loom and Vimeo.",
    "error": "We couldn't read the video length automatically.",
}
GONE = {"private", "not_found", "unavailable"}


class _Quiet:
    """yt-dlp logger that swallows output (stdout must stay pure JSON for the CLI)."""

    def debug(self, msg):
        pass

    info = warning = debug

    def error(self, msg):
        pass


def fmt_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def youtube_id(url: str) -> str | None:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        parts = [x for x in p.path.split("/") if x]
        if parts[:1] == ["watch"]:
            vid = (parse_qs(p.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            vid = parts[1]
        else:
            return None
    else:
        return None
    return vid if _YT_ID.match(vid or "") else None


_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso_duration(text: str) -> int | None:
    """'PT2M45S' -> 165; 'P0D' (live) -> None."""
    m = _ISO_DURATION.match(text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    total = d * 86400 + h * 3600 + mi * 60 + s
    return total or None


def classify_error(text: str) -> str:
    """Map a raw yt-dlp/HTTP error to a reason_code."""
    t = (text or "").lower()
    if "not a bot" in t or ("confirm you" in t and "bot" in t):
        return "bot_check"
    if "private video" in t or "video is private" in t:
        return "private"
    if ("age" in t and ("sign in" in t or "confirm your age" in t)) or "members-only" in t or "join this channel" in t:
        return "sign_in"
    if "unavailable" in t or "removed" in t or "does not exist" in t or "404" in t:
        return "unavailable"
    if "timed out" in t or "timeout" in t:
        return "timeout"
    return "error"


def _extract(url: str) -> dict:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
            "socket_timeout": 10, "extractor_retries": 0, "logger": _Quiet()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False, process=False) or {}


async def _youtube_api(video_id: str, transport=None) -> dict:
    """-> {"duration_s", "title"} or {"code"}. The key is read here and never returned or logged."""
    key = config.env("YOUTUBE_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as http:
            r = await http.get(YT_API, params={"part": "contentDetails,snippet", "id": video_id, "key": key})
    except httpx.TimeoutException:
        return {"code": "timeout", "raw": "YouTube Data API timeout"}
    except httpx.HTTPError as exc:
        return {"code": "error", "raw": f"YouTube Data API {type(exc).__name__}"}  # str(exc) may hold the URL + key
    if r.status_code != 200:
        try:
            why = r.json()["error"]["errors"][0]["reason"]  # quotaExceeded, keyInvalid, ...
        except Exception:
            why = "unknown"
        return {"code": "error", "raw": f"YouTube Data API HTTP {r.status_code} ({why})"}
    items = r.json().get("items") or []
    if not items:  # an API key sees public and unlisted videos; private or deleted ones don't come back
        return {"code": "not_found", "raw": "YouTube Data API: no such public video"}
    seconds = parse_iso_duration((items[0].get("contentDetails") or {}).get("duration", ""))
    title = ((items[0].get("snippet") or {}).get("title") or "")[:120] or None
    if not seconds:
        return {"code": "no_duration", "raw": "YouTube Data API: no duration (live?)", "title": title}
    return {"duration_s": seconds, "title": title}


@span("TOOL", "video.duration")
async def get_duration(url: str, extractor=_extract, transport=None) -> dict:
    """-> {url, duration_s, duration, status: known|unknown, reason_code, reason, source, title}.
    `reason` is always safe to show to users. Never raises."""
    out = {"url": url, "duration_s": None, "duration": None, "status": "unknown",
           "reason_code": None, "reason": None, "source": None, "title": None}
    raws: list[str] = []

    def known(seconds, source, title=None):
        out.update(duration_s=int(round(seconds)), duration=fmt_duration(seconds), status="known",
                   source=source, title=title, reason_code=None, reason=None)
        return out

    def unknown(code):
        out.update(reason_code=code, reason=FRIENDLY[code])
        if raws:  # for us, not for users
            event("video duration unknown: {code}", level="warning", code=code, url=url, raw=" | ".join(raws)[:500])
            log.info("video duration unknown for %s: %s", url, " | ".join(raws)[:300])
        return out

    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        return unknown("unsupported_host")

    vid = youtube_id(url)
    if vid and config.env("YOUTUBE_API_KEY"):
        api = await _youtube_api(vid, transport)
        if "duration_s" in api:
            return known(api["duration_s"], "youtube_api", api.get("title"))
        raws.append(api["raw"])
        if api["code"] in ("not_found", "no_duration"):
            out["title"] = api.get("title")
            return unknown(api["code"])  # a definite answer; yt-dlp can't do better

    try:
        info = await asyncio.wait_for(asyncio.to_thread(extractor, url), TIMEOUT_S)
    except asyncio.TimeoutError:
        raws.append(f"yt-dlp timed out after {TIMEOUT_S}s")
        return unknown("timeout")
    except Exception as exc:  # yt-dlp raises many kinds; all mean "couldn't read it"
        raw = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        raws.append(raw[:300])
        return unknown(classify_error(raw))
    duration = info.get("duration")
    out["title"] = (info.get("title") or "")[:120] or None
    if isinstance(duration, (int, float)) and duration > 0:
        return known(duration, "yt_dlp", out["title"])
    raws.append("yt-dlp: no duration in metadata")
    return unknown("no_duration")

"""Demo video duration from metadata only (yt-dlp, never downloads media).

Only called for links already classified as video hosts (YouTube/Loom/Vimeo) whose
host passed the link checker's SSRF guard. If the duration can't be read we say
"unknown" with the reason; we never guess.
"""
import asyncio
from urllib.parse import urlparse

from app.tracing import span

MAX_DEMO_SECONDS = 180
TIMEOUT_S = 20
VIDEO_HOSTS = ("youtube.com", "youtu.be", "loom.com", "vimeo.com")


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


def _extract(url: str) -> dict:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
            "socket_timeout": 10, "extractor_retries": 0, "logger": _Quiet()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False, process=False) or {}


def _reason(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    text = text.replace("ERROR: ", "")
    return text[:160]


@span("TOOL", "video.duration")
async def get_duration(url: str, extractor=_extract) -> dict:
    """-> {url, duration_s, duration, status: known|unknown, reason, title}. Never raises."""
    out = {"url": url, "duration_s": None, "duration": None, "status": "unknown",
           "reason": None, "title": None}
    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        out["reason"] = "not a supported video host"
        return out
    try:
        info = await asyncio.wait_for(asyncio.to_thread(extractor, url), TIMEOUT_S)
    except asyncio.TimeoutError:
        out["reason"] = f"metadata lookup timed out after {TIMEOUT_S}s"
        return out
    except Exception as exc:  # yt-dlp raises many kinds; all mean "couldn't read it"
        out["reason"] = _reason(exc)
        return out
    duration = info.get("duration")
    out["title"] = (info.get("title") or "")[:120] or None
    if isinstance(duration, (int, float)) and duration > 0:
        out.update(duration_s=int(round(duration)), duration=fmt_duration(duration), status="known")
    else:
        out["reason"] = "video page has no duration in its metadata"
    return out

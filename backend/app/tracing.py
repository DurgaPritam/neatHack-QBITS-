"""Thin wrapper around the neatlogs SDK so tracing never breaks an audit.

- init_tracing(): one-time SDK init with a secret-redacting mask.
- audit_context(): binds audit id + run kind ("test"/"real") + env ("prod"/"dev") to every span.
- event(): a timestamped step (retry, fallback, ...) inside the current span.
"""
import json
import logging
import re
import sys
from contextlib import ExitStack, contextmanager

from app import config

log = logging.getLogger(__name__)
_enabled = False

_SECRET_RX = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gsk_[A-Za-z0-9]{20,}"
    r"|ygbnp_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{30,}|Bearer\s+[A-Za-z0-9._\-]{16,})"
)


def redact(value):
    """Recursively replace anything that looks like one of our secrets."""
    if isinstance(value, str):
        out = _SECRET_RX.sub("[REDACTED]", value)
        for secret in (config.GITHUB_TOKEN, config.GROQ_API_KEY, config.NEATLOGS_API_KEY,
                       config.env("YOUTUBE_API_KEY")):
            if secret and len(secret) > 8:
                out = out.replace(secret, "[REDACTED]")
        return out
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    return value


def deploy_env() -> str:
    """Where this process runs: "prod" on the server, "dev" locally (NEATLOGS_ENV)."""
    return config.env("NEATLOGS_ENV", "dev")


def _mask(span: dict) -> dict:
    return redact(span)


def init_tracing(workflow_name: str = "prejudge") -> bool:
    """Initialise neatlogs once. Returns False (and keeps running) if unavailable."""
    global _enabled
    if _enabled:
        return True
    if not config.NEATLOGS_API_KEY:
        log.info("NEATLOGS_API_KEY not set; tracing disabled")
        return False
    try:
        import neatlogs

        neatlogs.init(
            api_key=config.NEATLOGS_API_KEY,
            workflow_name=workflow_name,
            tags=["neatHack", "prejudge", deploy_env()],
            mask=_mask,
        )
        _enabled = True
        # The SDK logs to stdout; move it to stderr so CLI stdout stays pure JSON.
        for h in logging.getLogger("neatlogs").handlers:
            if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
                h.setStream(sys.stderr)
    except Exception as exc:  # tracing must never take the app down
        log.warning("neatlogs init failed: %s", type(exc).__name__)
    return _enabled


def span(kind: str, name: str | None = None, **kwargs):
    """neatlogs.span decorator, or a no-op if the SDK can't be imported."""
    def deco(fn):
        try:
            import neatlogs

            return neatlogs.span(kind, name, **kwargs)(fn)
        except Exception:
            return fn

    return deco


@contextmanager
def audit_context(audit_id: str, run_kind: str, repo_url: str, phase: str = "audit"):
    """Group every span of one audit under its id, tagged test/real for filtering."""
    with ExitStack() as stack:
        if _enabled:
            try:
                import neatlogs

                stack.enter_context(neatlogs.identify(session_id=audit_id))
                stack.enter_context(neatlogs.trace(
                    f"prejudge.{phase}",
                    session_id=audit_id,
                    **{
                        "tag.tags": ["prejudge", run_kind, deploy_env()],
                        "metadata": json.dumps(
                            {"audit_id": audit_id, "run_kind": run_kind, "repo_url": repo_url,
                             "phase": phase, "env": deploy_env()}
                        ),
                    },
                ))
            except Exception as exc:
                log.warning("neatlogs audit context failed: %s", type(exc).__name__)
        yield


def event(message: str, level: str = "info", **data) -> None:
    """Record a retry/fallback/failure as a timestamped event in the active span."""
    if not _enabled:
        return
    try:
        import neatlogs

        neatlogs.log(message, level=level, **redact(data))
    except Exception:
        pass


def flush() -> None:
    if not _enabled:
        return
    try:
        import neatlogs

        neatlogs.flush(timeout_millis=10_000)
    except Exception:
        pass

"""Thin wrapper around the neatlogs SDK so tracing never breaks an audit."""
import logging

from app import config

log = logging.getLogger(__name__)
_enabled = False


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
            tags=["neatHack", "prejudge"],
        )
        _enabled = True
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


def flush() -> None:
    if not _enabled:
        return
    try:
        import neatlogs

        neatlogs.flush(timeout_millis=10_000)
    except Exception:
        pass

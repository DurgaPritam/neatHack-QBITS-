"""What the public API shows of the step log: raw tool and model errors stay in the database,
the neatlogs trace and the admin view; users get a friendly sentence instead."""

FRIENDLY_ERRORS = {
    # GitHub
    "not_found": "GitHub says this doesn't exist (or it's private).",
    "private": "The repo is private.",
    "rate_limited": "Hit a rate limit; waited or switched to another model and carried on.",
    "forbidden": "GitHub refused this request.",
    "network": "Couldn't reach the service; carried on without it.",
    "http_error": "The service returned an error; carried on without it.",
    "too_large": "The repo is too big to download in full; checked what we could.",
    "invalid_url": "That doesn't look like a GitHub repo URL.",
    # LLM
    "timeout": "The AI model took too long; carried on.",
    "connection": "Couldn't reach the AI model; carried on.",
    "model_not_found": "An AI model was retired; switched to another one.",
    "tool_use_failed": "The AI model sent a malformed answer; retried.",
    "daily_quota": "The AI models' daily budget ran out.",
    "invalid_tool_args": "The agent asked for something outside the repo; refused it.",
    "replay_miss": "No recorded answer for this step (replay mode).",
    # tools
    "duration_unknown": None,  # the step detail is already a friendly reason (video.FRIENDLY)
}
GENERIC = "This step failed; the audit carried on without it."


def friendly_step(step: dict) -> dict:
    kind = step.get("error_kind")
    if step.get("status") != "failed":
        return step
    if kind is None:
        if step.get("name", "").endswith("crashed"):
            return {**step, "detail": "Something broke on our side; the results so far are kept."}
        return step  # notes we wrote ourselves (roast rejected, salvage, ...)
    if kind.startswith("rate_limited"):
        kind = "rate_limited"
    if kind in FRIENDLY_ERRORS and FRIENDLY_ERRORS[kind] is None:
        return step
    if kind not in FRIENDLY_ERRORS:  # e.g. a Python exception name: not for users
        return {**step, "error_kind": "error", "detail": GENERIC}
    return {**step, "error_kind": kind, "detail": FRIENDLY_ERRORS[kind]}


def public_steps(steps: list[dict]) -> list[dict]:
    return [friendly_step(s) for s in steps]

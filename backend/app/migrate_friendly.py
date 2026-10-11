"""One-off: rewrite raw video-tool errors stored in old audits with today's friendly messages.

Audits saved before the friendly-errors change hold yt-dlp's raw text ("[youtube] <id>: Sign in
to confirm you're not a bot. Use --cookies-from-browser ...") in the video metadata, the demo
check, the score rows, the fix list and the step log. This replaces each with video.FRIENDLY.
Scores are not touched.

    python -m app.migrate_friendly              # dry run: list what would change
    python -m app.migrate_friendly --apply      # backup first (same folder as the DB), then rewrite
"""
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app.tools.video import FRIENDLY, classify_error

# yt-dlp's message: optional "ERROR: ", then "[extractor] id: text", up to a closing paren or the end
_RAW = re.compile(r"(?:ERROR:\s*)?\[(?:youtube|youtu\.be|vimeo|loom)[^\]]*\][^()]*(?:\([^()]*\)[^()]*)*", re.I)
_FRIENDLY_TEXT = set(FRIENDLY.values())


def friendly(text: str) -> str:
    """Replace every raw yt-dlp message inside text with its friendly sentence."""
    return _RAW.sub(lambda m: FRIENDLY[classify_error(m.group(0))].rstrip("."), text)


def _walk(value, path: str, changes: list[str]):
    if isinstance(value, str):
        new = friendly(value)
        if new != value:
            changes.append(path)
        return new
    if isinstance(value, dict):
        return {k: _walk(v, f"{path}.{k}", changes) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, f"{path}[{i}]", changes) for i, v in enumerate(value)]
    return value


def rewrite(result: dict | None, steps: list) -> tuple[dict | None, list, list[str]]:
    changes: list[str] = []
    if result:
        for m in result.get("videos") or []:
            reason = m.get("reason")
            if m.get("status") == "unknown" and reason and reason not in _FRIENDLY_TEXT:
                code = m.get("reason_code") if m.get("reason_code") in FRIENDLY else classify_error(reason)
                m.update(reason_code=code, reason=FRIENDLY[code])
                changes.append("result.videos[].reason")
        for c in result.get("checks") or []:
            data = c.get("data") or {}
            if c.get("id") == "demo_video" and data.get("reason") and data["reason"] not in _FRIENDLY_TEXT:
                code = classify_error(data["reason"])
                data.update(reason_code=code, reason=FRIENDLY[code])
                changes.append("result.checks.demo_video.data.reason")
        result = _walk(result, "result", changes)
    steps = _walk(steps, "steps", changes)
    return result, steps, changes


def backup(db_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{db_path.stem}-before-friendly-{stamp}.db")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as src, sqlite3.connect(dest) as d:
        src.backup(d)
    return dest


def run(db_path: Path, apply: bool) -> list[tuple[str, list[str]]]:
    if apply:
        print(f"backup: {backup(db_path)}")
    con = sqlite3.connect(db_path)
    done = []
    with con:
        for audit_id, result, steps in con.execute("SELECT id, result, steps FROM audits").fetchall():
            new_result, new_steps, changes = rewrite(json.loads(result) if result else None, json.loads(steps or "[]"))
            if not changes:
                continue
            done.append((audit_id, changes))
            if apply:
                con.execute("UPDATE audits SET result = ?, steps = ? WHERE id = ?",
                            (json.dumps(new_result) if new_result is not None else None, json.dumps(new_steps),
                             audit_id))
    con.close()
    return done


def main(argv: list[str]) -> None:
    apply = "--apply" in argv
    db_path = Path(config.env("PREJUDGE_DB", "prejudge.db"))
    done = run(db_path, apply)
    for audit_id, changes in done:
        print(f"{audit_id}: {len(changes)} field(s): {', '.join(sorted(set(changes)))}")
    print(f"{'rewrote' if apply else 'would rewrite'} {len(done)} audit(s)")


if __name__ == "__main__":
    main(sys.argv[1:])

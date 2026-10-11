"""Daily SQLite backup, run as its own container: `python -m app.backup`.

Uses SQLite's online backup API, so it's safe while the backend is writing. Copies go to
BACKUP_DIR as prejudge-YYYY-MM-DD.db; the newest BACKUP_KEEP are kept.
`python -m app.backup --once` takes one copy now and exits.
"""
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import config

log = logging.getLogger("prejudge.backup")
CHECK_EVERY_S = 3600


def backup_once(src: Path, dest_dir: Path, keep: int) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).date().isoformat()
    dest = dest_dir / f"prejudge-{day}.db"
    tmp = dest.with_suffix(".db.tmp")
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(tmp) as d:
        s.backup(d)
    tmp.replace(dest)
    for old in sorted(dest_dir.glob("prejudge-*.db"))[:-keep]:
        old.unlink()
    return dest


def due(dest_dir: Path) -> bool:
    day = datetime.now(timezone.utc).date().isoformat()
    return not (dest_dir / f"prejudge-{day}.db").exists()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    src = Path(config.env("PREJUDGE_DB", "/data/prejudge.db"))
    dest_dir = Path(config.env("BACKUP_DIR", "/backups"))
    keep = int(config.env("BACKUP_KEEP", "7"))
    once = "--once" in sys.argv
    while True:
        if once or due(dest_dir):
            try:
                if src.exists():
                    out = backup_once(src, dest_dir, keep)
                    log.info("backup written: %s (%d bytes)", out.name, out.stat().st_size)
                else:
                    log.info("no database yet at %s", src)
            except Exception as exc:  # keep the loop alive; the next check retries
                log.warning("backup failed: %s", exc)
        if once:
            return
        time.sleep(CHECK_EVERY_S)


if __name__ == "__main__":
    main()

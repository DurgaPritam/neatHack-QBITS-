import sqlite3

from app.backup import backup_once, due


def test_backup_copies_db_and_keeps_newest(tmp_path):
    src = tmp_path / "live.db"
    with sqlite3.connect(src) as c:
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (42)")
    out_dir = tmp_path / "backups"
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        (out_dir / f"prejudge-{day}.db").parent.mkdir(exist_ok=True)
        (out_dir / f"prejudge-{day}.db").write_bytes(b"old")
    assert due(out_dir)
    dest = backup_once(src, out_dir, keep=2)
    assert not due(out_dir)
    with sqlite3.connect(dest) as c:
        assert c.execute("SELECT x FROM t").fetchone() == (42,)
    assert sorted(p.name for p in out_dir.iterdir()) == ["prejudge-2026-10-03.db", dest.name]

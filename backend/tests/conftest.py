"""Tests never send traces, call real APIs with real keys, or touch the real database."""
import os
import tempfile

import pytest

from app import config, db

config.NEATLOGS_API_KEY = ""
os.environ["PREJUDGE_DB"] = os.path.join(tempfile.mkdtemp(prefix="prejudge-test-"), "test.db")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file, so roast memory etc. can't leak between tests."""
    path = str(tmp_path / "isolated.db")
    monkeypatch.setenv("PREJUDGE_DB", path)
    db.connect(path)
    yield

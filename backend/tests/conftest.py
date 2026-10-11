"""Tests never send traces, call real APIs with real keys, or touch the real database."""
import os
import tempfile

# Before app.config runs load_dotenv (which never overrides a variable that is already set):
# the neatlogs SDK reads NEATLOGS_API_KEY from os.environ by itself and would start exporting.
for _key in ("NEATLOGS_API_KEY", "GROQ_API_KEY", "GITHUB_TOKEN", "YOUTUBE_API_KEY"):
    os.environ[_key] = ""
os.environ["NEATLOGS_DISABLE_EXPORT"] = "true"

import pytest  # noqa: E402

from app import config, db  # noqa: E402

config.NEATLOGS_API_KEY = ""
# Tests pin their own settings instead of inheriting the developer's .env
os.environ["LLM_MODE"] = "live"      # tests use scripted fake clients; replay has its own tests
os.environ["JUDGE_MODELS"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["PREJUDGE_DB"] = os.path.join(tempfile.mkdtemp(prefix="prejudge-test-"), "test.db")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file, so roast memory etc. can't leak between tests."""
    path = str(tmp_path / "isolated.db")
    monkeypatch.setenv("PREJUDGE_DB", path)
    db.connect(path)
    yield

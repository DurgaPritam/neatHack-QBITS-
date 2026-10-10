"""Tests never send traces, call real APIs with real keys, or touch the real database."""
import os
import tempfile

from app import config

config.NEATLOGS_API_KEY = ""
os.environ["PREJUDGE_DB"] = os.path.join(tempfile.mkdtemp(prefix="prejudge-test-"), "test.db")

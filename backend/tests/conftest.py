"""Tests never send traces or call real APIs with real keys."""
from app import config

config.NEATLOGS_API_KEY = ""

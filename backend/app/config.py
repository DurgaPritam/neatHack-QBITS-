"""Settings loaded from backend/.env. Keys are never logged."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


GITHUB_TOKEN = env("GITHUB_TOKEN")
NEATLOGS_API_KEY = env("NEATLOGS_API_KEY")
GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL")
GROQ_FALLBACK_MODEL = env("GROQ_FALLBACK_MODEL")

HTTP_TIMEOUT = float(env("HTTP_TIMEOUT", "10"))

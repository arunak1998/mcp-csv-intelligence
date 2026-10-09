"""Environment-driven configuration shared by the agents and the UI."""

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-5-mini"


def require_env(name: str) -> str:
    """Return a required environment variable or fail with a message that names it."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set. See .env.example.")
    return value

"""All configuration, read from the environment (a local .env file is loaded automatically)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-5-mini"
PRIVACY_MODES = ("standard", "strict")


@dataclass(frozen=True)
class Settings:
    upload_dir: Path
    mcp_host: str
    mcp_port: int
    mcp_url: str
    privacy_mode: str
    max_result_rows: int
    query_timeout_seconds: float
    insight_max_rows: int


def require_env(name: str) -> str:
    """Return a required environment variable or fail with a message that names it."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set. See .env.example.")
    return value


def _privacy_mode(value: str) -> str:
    if value not in PRIVACY_MODES:
        raise RuntimeError(f"PRIVACY_MODE must be one of {PRIVACY_MODES}, got {value!r}")
    return value


def load_settings() -> Settings:
    port = int(os.getenv("MCP_PORT", "8050"))
    return Settings(
        upload_dir=Path(os.getenv("UPLOAD_DIR", "data/uploads")),
        mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
        mcp_port=port,
        mcp_url=os.getenv("MCP_SERVER_URL", f"http://localhost:{port}/mcp"),
        privacy_mode=_privacy_mode(os.getenv("PRIVACY_MODE", "standard")),
        max_result_rows=int(os.getenv("MAX_RESULT_ROWS", "1000")),
        query_timeout_seconds=float(os.getenv("QUERY_TIMEOUT_SECONDS", "10")),
        insight_max_rows=int(os.getenv("INSIGHT_MAX_ROWS", "20")),
    )

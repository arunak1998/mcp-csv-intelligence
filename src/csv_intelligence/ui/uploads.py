"""Where the UI saves the uploaded CSV. The MCP server exposes the same folder (see FILE_LOCATION)."""

import os
from pathlib import Path


def upload_dir() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "data/uploads"))


def clear_uploads() -> None:
    for path in upload_dir().glob("*.csv"):
        path.unlink()


def save_upload(name: str, content: bytes) -> Path:
    """Save the file as the only CSV in the folder, because the server exposes every CSV it finds."""
    clear_uploads()
    upload_dir().mkdir(parents=True, exist_ok=True)
    path = upload_dir() / Path(name).name
    path.write_bytes(content)
    return path

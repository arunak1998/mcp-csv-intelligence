"""Turn an uploaded CSV into the dataset the MCP server queries (Parquet + profile in the upload folder)."""

import tempfile
from pathlib import Path
from typing import Any

from csv_intelligence.data.datasets import remove_all_datasets
from csv_intelligence.data.ingest import ingest_csv
from csv_intelligence.settings import load_settings


def save_upload(
    name: str, content: bytes, choices: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Convert the uploaded bytes to the active dataset and return its profile. The CSV is not kept."""
    upload_dir = load_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".csv", dir=upload_dir, delete=False) as staged:
        staged.write(content)
    try:
        return ingest_csv(Path(staged.name), upload_dir, Path(name).name, choices)
    finally:
        Path(staged.name).unlink(missing_ok=True)


def clear_uploads() -> None:
    remove_all_datasets(load_settings().upload_dir)

"""Two-step upload: stage the CSV and scan it for personal data, then convert it with the user's choices.

Staged files live in <upload dir>/.staging/, which the MCP server never lists (it only serves *.parquet).
"""

import re
import secrets
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from csv_intelligence.data.ingest import ingest_csv, read_csv
from csv_intelligence.data.pii import scan_pii
from csv_intelligence.formatting import format_value

PREVIEW_ROWS = 5
UPLOAD_ID = re.compile(r"^[0-9a-f]{16}$")


class UnknownUploadError(LookupError):
    """The upload id does not match a staged file (expired, already converted, or invalid)."""


def staging_dir(upload_dir: Path) -> Path:
    return upload_dir / ".staging"


def stage_upload(upload_dir: Path, filename: str, content: bytes) -> dict[str, Any]:
    """Keep the CSV aside and describe it for the review step: columns, PII findings, a short preview.

    Only one upload is staged at a time. Raises ValueError when the file can't be read as a CSV.
    """
    folder = staging_dir(upload_dir)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    upload_id = secrets.token_hex(8)
    path = folder / f"{upload_id}.csv"
    path.write_bytes(content)
    (folder / f"{upload_id}.name").write_text(Path(filename).name, encoding="utf-8")
    try:
        df = read_csv(path)
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"Could not read {Path(filename).name} as a CSV: {error}") from error
    return {
        "upload_id": upload_id,
        "filename": Path(filename).name,
        "row_count": df.height,
        "columns": [{"name": name, "dtype": str(dtype)} for name, dtype in df.schema.items()],
        "pii": [asdict(finding) for finding in scan_pii(df)],
        "preview": [[format_value(value) for value in row] for row in df.head(PREVIEW_ROWS).iter_rows()],
    }


def ingest_staged(upload_dir: Path, upload_id: str, choices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Convert the staged CSV into the active dataset with the chosen masks/renames; return its profile."""
    folder = staging_dir(upload_dir)
    path = folder / f"{upload_id}.csv"
    if not UPLOAD_ID.fullmatch(upload_id) or not path.is_file():
        raise UnknownUploadError("This upload is no longer waiting for review. Please upload the file again.")
    filename = (folder / f"{upload_id}.name").read_text(encoding="utf-8")
    try:
        return ingest_csv(path, upload_dir, filename, choices)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

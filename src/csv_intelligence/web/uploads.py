"""Two-step upload: stage the file and scan it for personal data, then convert it with the user's choices.

CSV and Excel (.xlsx, .xlsm, .xls) are accepted; Excel uses its first sheet. Staged files live in
<upload dir>/.staging/, which the MCP server never lists (it only serves *.parquet).
"""

import re
import secrets
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from csv_intelligence.data.ingest import (
    EXCEL_SUFFIXES,
    UnsupportedFileError,
    excel_sheet_names,
    ingest_file,
    read_table,
)
from csv_intelligence.data.pii import scan_pii
from csv_intelligence.formatting import format_value
from csv_intelligence.timing import Timer

PREVIEW_ROWS = 5
UPLOAD_ID = re.compile(r"^[0-9a-f]{16}$")


class UnknownUploadError(LookupError):
    """The upload id does not match a staged file (expired, already converted, or invalid)."""


def staging_dir(upload_dir: Path) -> Path:
    return upload_dir / ".staging"


def _staged_file(folder: Path, upload_id: str) -> Path | None:
    if not UPLOAD_ID.fullmatch(upload_id):
        return None
    return next((path for path in folder.glob(f"{upload_id}.*") if path.suffix != ".name"), None)


def _sheets(path: Path) -> list[str] | None:
    """Sheet names of an Excel file (the first one is used), or None for a CSV."""
    return excel_sheet_names(path) if path.suffix.lower() in EXCEL_SUFFIXES else None


def stage_upload(upload_dir: Path, filename: str, content: bytes) -> dict[str, Any]:
    """Keep the file aside and describe it for the review step: columns, PII findings, a short preview.

    Only one upload is staged at a time. Raises ValueError when the file type is not supported or
    the file can't be read.
    """
    name = Path(filename).name
    timer = Timer()
    folder = staging_dir(upload_dir)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    upload_id = secrets.token_hex(8)
    path = folder / f"{upload_id}{Path(name).suffix.lower()}"
    path.write_bytes(content)
    (folder / f"{upload_id}.name").write_text(name, encoding="utf-8")
    try:
        with timer.step("read_file"):
            df = read_table(path)
            sheets = _sheets(path)
    except UnsupportedFileError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"Could not read {name}: {error}") from error
    with timer.step("pii_scan"):
        findings = scan_pii(df)
    return {
        "upload_id": upload_id,
        "filename": name,
        "sheets": sheets,
        "row_count": df.height,
        "columns": [{"name": column, "dtype": str(dtype)} for column, dtype in df.schema.items()],
        "pii": [asdict(finding) for finding in findings],
        "preview": [[format_value(value) for value in row] for row in df.head(PREVIEW_ROWS).iter_rows()],
        "timings_ms": timer.report(),
    }


def ingest_staged(upload_dir: Path, upload_id: str, choices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Convert the staged file into the active dataset with the chosen masks/renames.

    Returns the profile plus timings_ms (read_file, privacy, write_parquet, profile, total).
    """
    folder = staging_dir(upload_dir)
    path = _staged_file(folder, upload_id)
    if path is None:
        raise UnknownUploadError("This upload is no longer waiting for review. Please upload the file again.")
    filename = (folder / f"{upload_id}.name").read_text(encoding="utf-8")
    timer = Timer()
    try:
        profile = ingest_file(path, upload_dir, filename, choices, timer)
        return {**profile, "timings_ms": timer.report()}
    finally:
        shutil.rmtree(folder, ignore_errors=True)

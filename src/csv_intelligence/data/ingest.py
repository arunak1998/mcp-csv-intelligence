"""Turn an uploaded CSV or Excel file into the dataset the MCP server queries: Parquet + a cached profile."""

from pathlib import Path
from typing import Any

import fastexcel
import polars as pl

from csv_intelligence.data.datasets import dataset_name, parquet_path, profile_path, remove_all_datasets
from csv_intelligence.data.pii import apply_privacy_choices, scan_pii
from csv_intelligence.data.profile import build_profile, save_profile
from csv_intelligence.timing import Timer

# Rows Polars looks at to guess column types; enough to see past a few blank or odd early rows.
SCHEMA_INFERENCE_ROWS = 10_000
EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
SUPPORTED_SUFFIXES = (".csv", *EXCEL_SUFFIXES)
# Excel readers name a column with an empty header like this.
UNNAMED_PREFIX = "__UNNAMED__"


class UnsupportedFileError(ValueError):
    """The upload is not a CSV or Excel file."""


def clean_column_names(columns: list[str]) -> list[str]:
    """Strip stray whitespace from headers and name blank ones, so SQL can refer to every column."""
    cleaned = []
    for index, column in enumerate(columns):
        name = column.strip()
        cleaned.append(f"column_{index + 1}" if not name or name.startswith(UNNAMED_PREFIX) else name)
    return cleaned


def _with_clean_headers(df: pl.DataFrame) -> pl.DataFrame:
    return df.rename(dict(zip(df.columns, clean_column_names(df.columns), strict=True)))


def read_csv(path: Path) -> pl.DataFrame:
    """Read a CSV with typed columns (numbers and dates are detected) and clean headers."""
    df = pl.read_csv(
        path,
        try_parse_dates=True,
        infer_schema_length=SCHEMA_INFERENCE_ROWS,
        encoding="utf8-lossy",
    )
    return _with_clean_headers(df)


def excel_sheet_names(path: Path) -> list[str]:
    return fastexcel.read_excel(path).sheet_names


def read_excel(path: Path) -> pl.DataFrame:
    """Read the first sheet of an Excel workbook (.xlsx, .xlsm, .xls) with typed columns and clean headers."""
    return _with_clean_headers(pl.read_excel(path, sheet_id=1, infer_schema_length=SCHEMA_INFERENCE_ROWS))


def read_table(path: Path) -> pl.DataFrame:
    """Read a CSV or the first sheet of an Excel file, chosen by the file extension."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)
    if suffix in EXCEL_SUFFIXES:
        return read_excel(path)
    allowed = ", ".join(SUPPORTED_SUFFIXES)
    raise UnsupportedFileError(
        f"Upload a CSV or Excel file ({allowed}), not {suffix or 'a file with no extension'}"
    )


def save_dataset(
    df: pl.DataFrame,
    upload_dir: Path,
    source_file: str,
    privacy: dict[str, dict[str, Any]] | None = None,
    timer: Timer | None = None,
) -> dict[str, Any]:
    """Store df as the only dataset in upload_dir and return its profile."""
    timer = timer or Timer()
    name = dataset_name(source_file)
    upload_dir.mkdir(parents=True, exist_ok=True)
    remove_all_datasets(upload_dir)
    with timer.step("write_parquet"):
        df.write_parquet(parquet_path(upload_dir, name))
    with timer.step("profile"):
        profile = build_profile(df, name, source_file, privacy)
        save_profile(profile, profile_path(upload_dir, name))
    return profile


def ingest_file(
    path: Path,
    upload_dir: Path,
    source_file: str,
    choices: dict[str, dict[str, Any]] | None = None,
    timer: Timer | None = None,
) -> dict[str, Any]:
    """Convert a CSV or Excel file to Parquet + profile, applying the user's mask/rename choices.

    The uploaded file is not kept. Masking happens before anything is written, so the stored dataset
    never holds the raw values. Pass a timer to get read_file, privacy, write_parquet and profile timings.
    """
    timer = timer or Timer()
    with timer.step("read_file"):
        df = read_table(path)
    with timer.step("privacy"):
        df, privacy = apply_privacy_choices(df, scan_pii(df), choices or {})
    profile = save_dataset(df, upload_dir, source_file, privacy, timer)
    path.unlink(missing_ok=True)
    return profile

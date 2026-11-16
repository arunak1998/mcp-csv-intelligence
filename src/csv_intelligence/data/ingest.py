"""Turn an uploaded CSV into the dataset the MCP server queries: a Parquet file plus a cached profile."""

from pathlib import Path
from typing import Any

import polars as pl

from csv_intelligence.data.datasets import dataset_name, parquet_path, profile_path, remove_all_datasets
from csv_intelligence.data.pii import apply_privacy_choices, scan_pii
from csv_intelligence.data.profile import build_profile, save_profile

# Rows Polars looks at to guess column types; enough to see past a few blank or odd early rows.
SCHEMA_INFERENCE_ROWS = 10_000


def clean_column_names(columns: list[str]) -> list[str]:
    """Strip stray whitespace from headers and name blank ones, so SQL can refer to every column."""
    return [column.strip() or f"column_{index + 1}" for index, column in enumerate(columns)]


def read_csv(path: Path) -> pl.DataFrame:
    """Read a CSV with typed columns (numbers and dates are detected) and clean headers."""
    df = pl.read_csv(
        path,
        try_parse_dates=True,
        infer_schema_length=SCHEMA_INFERENCE_ROWS,
        encoding="utf8-lossy",
    )
    return df.rename(dict(zip(df.columns, clean_column_names(df.columns), strict=True)))


def save_dataset(
    df: pl.DataFrame, upload_dir: Path, source_file: str, privacy: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Store df as the only dataset in upload_dir and return its profile."""
    name = dataset_name(source_file)
    upload_dir.mkdir(parents=True, exist_ok=True)
    remove_all_datasets(upload_dir)
    df.write_parquet(parquet_path(upload_dir, name))
    profile = build_profile(df, name, source_file, privacy)
    save_profile(profile, profile_path(upload_dir, name))
    return profile


def ingest_csv(
    csv_path: Path,
    upload_dir: Path,
    source_file: str,
    choices: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert a CSV to Parquet + profile, applying the user's mask/rename choices; the CSV is not kept.

    Masking happens before anything is written, so the stored dataset never holds the raw values.
    """
    df = read_csv(csv_path)
    df, privacy = apply_privacy_choices(df, scan_pii(df), choices or {})
    profile = save_dataset(df, upload_dir, source_file, privacy)
    csv_path.unlink(missing_ok=True)
    return profile

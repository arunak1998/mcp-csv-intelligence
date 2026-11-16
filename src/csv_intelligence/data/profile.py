"""Schema + summary statistics for a dataset, computed once at upload and cached as JSON."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl


def _scalar(value: Any) -> Any:
    """Make a statistic JSON-friendly (dates become ISO strings, floats are rounded)."""
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 4)
    return value


def column_stats(series: pl.Series) -> dict[str, Any]:
    """Counts for every column, plus min/max/mean for numbers and min/max for dates.

    Text columns get counts only: their min/max would be real values from the file.
    """
    stats: dict[str, Any] = {
        "name": series.name,
        "dtype": str(series.dtype),
        "nulls": series.null_count(),
        "distinct": series.n_unique(),
    }
    if series.dtype.is_numeric() and series.null_count() < len(series):
        stats.update(min=_scalar(series.min()), max=_scalar(series.max()), mean=_scalar(series.mean()))
    elif series.dtype.is_temporal() and series.null_count() < len(series):
        stats.update(min=_scalar(series.min()), max=_scalar(series.max()))
    return stats


def build_profile(df: pl.DataFrame, name: str, source_file: str) -> dict[str, Any]:
    return {
        "dataset": name,
        "source_file": source_file,
        "row_count": df.height,
        "columns": [column_stats(df[column]) for column in df.columns],
    }


def save_profile(profile: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")


def load_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

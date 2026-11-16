"""Where datasets live on disk: <name>.parquet plus its cached <name>.profile.json in the upload folder."""

import re
from pathlib import Path

UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")


def dataset_name(filename: str) -> str:
    """Turn an uploaded file name into a safe dataset name, e.g. 'Sales 2025.csv' -> 'Sales_2025'."""
    name = UNSAFE_CHARACTERS.sub("_", Path(filename).stem).strip("_")
    return name or "dataset"


def parquet_path(upload_dir: Path, name: str) -> Path:
    return upload_dir / f"{name}.parquet"


def profile_path(upload_dir: Path, name: str) -> Path:
    return upload_dir / f"{name}.profile.json"


def list_datasets(upload_dir: Path) -> list[str]:
    return sorted(path.stem for path in upload_dir.glob("*.parquet"))


def remove_all_datasets(upload_dir: Path) -> None:
    for pattern in ("*.parquet", "*.profile.json"):
        for path in upload_dir.glob(pattern):
            path.unlink()

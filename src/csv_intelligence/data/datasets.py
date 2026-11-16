"""Where datasets live on disk: <name>.parquet plus its cached <name>.profile.json in the upload folder."""

import re
from pathlib import Path

UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class DatasetNotFoundError(LookupError):
    """The name is not a dataset in the upload folder (or tries to point outside it)."""


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


def resolve_inside_uploads(upload_dir: Path, name: str, suffix: str) -> Path:
    """Return the dataset file for name, refusing anything that is not an existing file in upload_dir.

    Names are restricted to letters, digits, '_' and '-', and the resolved path must still be inside
    upload_dir, so '../', absolute paths and symlinks pointing elsewhere are all rejected.
    """
    if not SAFE_NAME.fullmatch(name):
        raise DatasetNotFoundError(f"{name!r} is not a valid dataset name")
    root = upload_dir.resolve()
    path = (upload_dir / f"{name}{suffix}").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise DatasetNotFoundError(f"No dataset named {name!r}")
    return path

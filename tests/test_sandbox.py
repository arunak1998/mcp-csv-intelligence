import pytest

from csv_intelligence.data.datasets import DatasetNotFoundError, resolve_inside_uploads


@pytest.fixture
def folder(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "sales.parquet").write_bytes(b"data")
    return uploads


def test_existing_dataset_resolves_inside_the_folder(folder):
    assert resolve_inside_uploads(folder, "sales", ".parquet") == (folder / "sales.parquet").resolve()


@pytest.mark.parametrize("name", ["../sales", "/etc/passwd", "sales/../../x", "sales.parquet", "", "a b"])
def test_names_with_path_characters_are_refused(folder, name):
    with pytest.raises(DatasetNotFoundError, match="not a valid dataset name"):
        resolve_inside_uploads(folder, name, ".parquet")


def test_missing_dataset_is_refused(folder):
    with pytest.raises(DatasetNotFoundError, match="No dataset"):
        resolve_inside_uploads(folder, "missing", ".parquet")


def test_symlink_out_of_the_folder_is_refused(folder, tmp_path):
    outside = tmp_path / "secret.parquet"
    outside.write_bytes(b"not yours")
    (folder / "leak.parquet").symlink_to(outside)
    with pytest.raises(DatasetNotFoundError, match="No dataset"):
        resolve_inside_uploads(folder, "leak", ".parquet")

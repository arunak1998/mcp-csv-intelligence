import polars as pl

from csv_intelligence.ui.uploads import clear_uploads, save_upload


def test_save_upload_converts_to_parquet_and_keeps_no_csv(upload_dir):
    profile = save_upload("Sales 2025.csv", b"region,revenue\nNorth,10\nSouth,20\n")

    assert profile["dataset"] == "Sales_2025" and profile["row_count"] == 2
    assert pl.read_parquet(upload_dir / "Sales_2025.parquet")["revenue"].sum() == 30
    assert list(upload_dir.glob("*.csv")) == []


def test_save_upload_keeps_a_single_dataset(upload_dir):
    save_upload("first.csv", b"a\n1\n")
    save_upload("second.csv", b"a\n2\n")
    assert sorted(path.name for path in upload_dir.iterdir()) == ["second.parquet", "second.profile.json"]


def test_save_upload_applies_privacy_choices(upload_dir):
    save_upload("people.csv", b"email,n\nann@example.com,1\n", {"email": {"mask": True}})
    assert pl.read_parquet(upload_dir / "people.parquet")["email"][0].startswith("email_")


def test_a_bad_upload_leaves_no_staged_file(upload_dir):
    try:
        save_upload("bad.csv", b"a,b\n1\n2,3,4,5\n")
    except Exception:
        pass
    assert list(upload_dir.glob("*.csv")) == []


def test_clear_uploads_removes_the_dataset(upload_dir):
    save_upload("x.csv", b"a\n1\n")
    clear_uploads()
    assert list(upload_dir.iterdir()) == []

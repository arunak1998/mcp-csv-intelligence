import polars as pl

from csv_intelligence.data import datasets
from csv_intelligence.data.ingest import clean_column_names, ingest_csv, read_csv
from csv_intelligence.data.profile import column_stats, load_profile


def test_dataset_name_is_safe_for_paths():
    assert datasets.dataset_name("Sales 2025 (final).csv") == "Sales_2025_final"
    assert datasets.dataset_name("../../etc/passwd") == "passwd"
    assert datasets.dataset_name("###.csv") == "dataset"


def test_clean_column_names_strips_and_fills_blanks():
    assert clean_column_names([" region ", "", "revenue"]) == ["region", "column_2", "revenue"]


def test_read_csv_detects_dates_and_numbers(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text(" day ,amount\n2025-01-02,10\n2025-01-03,12.5\n")
    df = read_csv(path)
    assert df.schema == {"day": pl.Date, "amount": pl.Float64}


def test_ingest_writes_parquet_and_profile_and_drops_the_csv(sales_dataset, upload_dir):
    assert sales_dataset == "sample_sales"
    assert datasets.parquet_path(upload_dir, sales_dataset).exists()
    assert list(upload_dir.glob("*.csv")) == []

    profile = load_profile(datasets.profile_path(upload_dir, sales_dataset))
    assert profile["row_count"] == 120
    assert [c["name"] for c in profile["columns"]][:3] == ["order_id", "order_date", "region"]


def test_ingest_keeps_only_the_latest_dataset(upload_dir, tmp_path):
    for name in ("first.csv", "second.csv"):
        (tmp_path / name).write_text("a\n1\n")
        ingest_csv(tmp_path / name, upload_dir, name)
    assert datasets.list_datasets(upload_dir) == ["second"]


def test_text_columns_get_counts_but_no_values():
    stats = column_stats(pl.Series("region", ["North", "South", None]))
    assert stats == {"name": "region", "dtype": "String", "nulls": 1, "distinct": 3}


def test_numeric_and_date_columns_get_ranges():
    numbers = column_stats(pl.Series("n", [1, 2, 3]))
    assert (numbers["min"], numbers["max"], numbers["mean"]) == (1, 3, 2.0)

    days = column_stats(pl.Series("d", ["2025-01-01", "2025-03-01"]).str.to_date())
    assert (days["min"], days["max"]) == ("2025-01-01", "2025-03-01")
    assert "mean" not in days

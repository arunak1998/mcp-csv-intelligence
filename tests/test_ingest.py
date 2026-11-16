from datetime import date

import polars as pl
import pytest
import xlsxwriter

from csv_intelligence.data import datasets
from csv_intelligence.data.ingest import (
    UnsupportedFileError,
    clean_column_names,
    excel_sheet_names,
    ingest_file,
    read_csv,
    read_table,
)
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
        ingest_file(tmp_path / name, upload_dir, name)
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


def write_workbook(path, sheets: dict) -> None:
    with xlsxwriter.Workbook(path) as workbook:
        for sheet, df in sheets.items():
            df.write_excel(workbook, worksheet=sheet)


def test_clean_column_names_renames_excel_unnamed_headers():
    assert clean_column_names(["__UNNAMED__0", "revenue"]) == ["column_1", "revenue"]


def test_read_table_reads_the_first_excel_sheet_with_types(tmp_path):
    path = tmp_path / "book.xlsx"
    sales = pl.DataFrame({" Order Date ": [date(2025, 1, 2), date(2025, 2, 3)], "Revenue": [10.5, 20.0]})
    write_workbook(path, {"Sales": sales, "Other": pl.DataFrame({"x": [1]})})

    df = read_table(path)

    assert df.schema == {"Order Date": pl.Date, "Revenue": pl.Float64}
    assert excel_sheet_names(path) == ["Sales", "Other"]


def test_read_table_picks_the_reader_by_extension(tmp_path):
    csv = tmp_path / "A.CSV"
    csv.write_text("a\n1\n")
    assert read_table(csv)["a"].to_list() == [1]
    with pytest.raises(UnsupportedFileError, match="CSV or Excel"):
        read_table(tmp_path / "notes.txt")


def test_ingest_file_converts_excel_to_parquet(upload_dir, tmp_path):
    path = tmp_path / "Q1 Sales.xlsx"
    write_workbook(path, {"Sales": pl.DataFrame({"region": ["North", "South"], "revenue": [10, 20]})})

    profile = ingest_file(path, upload_dir, "Q1 Sales.xlsx")

    assert profile["dataset"] == "Q1_Sales" and profile["row_count"] == 2
    assert pl.read_parquet(upload_dir / "Q1_Sales.parquet")["revenue"].sum() == 30
    assert not path.exists()


def test_warm_up_excel_reader_imports_pyarrow_only_when_installed(monkeypatch):
    import importlib

    from csv_intelligence.data import ingest

    imported = []
    monkeypatch.setattr(importlib, "import_module", imported.append)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    ingest.warm_up_excel_reader()
    assert imported == []

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    ingest.warm_up_excel_reader()
    assert imported == ["pyarrow"]

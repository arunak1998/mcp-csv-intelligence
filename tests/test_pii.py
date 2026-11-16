import polars as pl
import pytest

from csv_intelligence.data.ingest import ingest_file
from csv_intelligence.data.pii import PiiFinding, apply_privacy_choices, scan_pii

PEOPLE = pl.DataFrame(
    {
        "Customer Name": ["Ann Lee", "Bo Chan", "Ann Lee"],
        "contact": ["ann@example.com", "bo@example.org", "ann@example.com"],
        "mobile": ["+1 (555) 010-2000", "555-010-3000", None],
        "product": ["Pen Set", "Desk", "Pen Set"],
        "order_id": [1001, 1002, 1003],
    }
)


def test_scan_finds_emails_phones_and_names():
    assert scan_pii(PEOPLE) == [
        PiiFinding("Customer Name", "name", "the column name suggests a name"),
        PiiFinding("contact", "email", "100% of sampled values look like emails"),
        PiiFinding("mobile", "phone", "100% of sampled values look like phones"),
    ]


def test_scan_ignores_ordinary_columns():
    df = pl.DataFrame({"product_name": ["Pen Set"], "units": [1234567], "region": ["North"]})
    assert scan_pii(df) == []


def test_masking_replaces_values_with_stable_tokens():
    df, flags = apply_privacy_choices(PEOPLE, scan_pii(PEOPLE), {"contact": {"mask": True}})

    tokens = df["contact"].to_list()
    assert all(token.startswith("email_") for token in tokens)
    assert tokens[0] == tokens[2] != tokens[1]
    assert "ann@example.com" not in df["contact"].to_list()
    assert flags["contact"] == {"pii": "email", "masked": True}
    assert flags["Customer Name"] == {"pii": "name", "masked": False}


def test_masking_keeps_nulls():
    df, _ = apply_privacy_choices(PEOPLE, scan_pii(PEOPLE), {"mobile": {"mask": True}})
    assert df["mobile"].null_count() == 1


def test_rename_changes_the_header_and_flags_follow():
    df, flags = apply_privacy_choices(PEOPLE, scan_pii(PEOPLE), {"Customer Name": {"rename": "buyer"}})
    assert "buyer" in df.columns and "Customer Name" not in df.columns
    assert flags["buyer"] == {"pii": "name", "masked": False}


def test_rename_to_an_existing_column_is_refused():
    with pytest.raises(ValueError, match="same name"):
        apply_privacy_choices(PEOPLE, [], {"contact": {"rename": "product"}})


def test_unknown_columns_are_refused():
    with pytest.raises(ValueError, match="Unknown columns"):
        apply_privacy_choices(PEOPLE, [], {"nope": {"mask": True}})


def test_ingest_never_stores_masked_values_and_hides_their_stats(upload_dir, tmp_path):
    csv = tmp_path / "people.csv"
    PEOPLE.write_csv(csv)

    profile = ingest_file(csv, upload_dir, "people.csv", {"contact": {"mask": True}})

    stored = pl.read_parquet(upload_dir / "people.parquet")
    assert "ann@example.com" not in stored["contact"].to_list()
    contact = next(column for column in profile["columns"] if column["name"] == "contact")
    assert contact["masked"] is True and contact["pii"] == "email"
    assert "min" not in contact

import json

import pytest

from csv_intelligence.agents.privacy import insight_decision, local_summary, schema_for_llm
from csv_intelligence.sql.guard import parse_select

PROFILE = {
    "dataset": "customers_secret",
    "source_file": "customers_secret.csv",
    "row_count": 100,
    "columns": [
        {
            "name": "order_id",
            "dtype": "Int64",
            "nulls": 0,
            "distinct": 100,
            "min": 1,
            "max": 100,
            "mean": 50.5,
        },
        {"name": "region", "dtype": "String", "nulls": 0, "distinct": 4},
        {"name": "revenue", "dtype": "Int64", "nulls": 0, "distinct": 60, "min": 5, "max": 900, "mean": 80.0},
        {"name": "email", "dtype": "String", "nulls": 0, "distinct": 90, "pii": "email", "masked": False},
        {"name": "phone", "dtype": "String", "nulls": 0, "distinct": 90, "pii": "phone", "masked": True},
    ],
}
SMALL = {
    "columns": ["region", "total"],
    "rows": [["North", 10], ["South", 30]],
    "row_count": 2,
    "truncated": False,
}


def decide(sql, mode="standard", result=SMALL, max_rows=20):
    return insight_decision(mode, parse_select(sql), result, PROFILE, max_rows)


def test_schema_for_llm_has_stats_but_no_file_name_or_pii_kind():
    payload = schema_for_llm(PROFILE)
    text = json.dumps(payload)
    assert "customers_secret" not in text and "pii" not in text
    assert payload["columns"][2] == {
        "name": "revenue",
        "dtype": "Int64",
        "nulls": 0,
        "distinct": 60,
        "min": 5,
        "max": 900,
        "mean": 80.0,
    }
    assert payload["columns"][4]["masked"] is True


def test_small_aggregate_may_be_sent():
    decision = decide("SELECT region, SUM(revenue) AS total FROM self GROUP BY region")
    assert decision.allowed
    assert "2-row aggregate" in decision.reason


def test_strict_mode_never_sends_results():
    decision = decide("SELECT region, SUM(revenue) AS total FROM self GROUP BY region", mode="strict")
    assert not decision.allowed and "Strict mode" in decision.reason


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("SELECT region, revenue FROM self", "row-level"),
        ("SELECT order_id, SUM(revenue) AS r FROM self GROUP BY order_id", "unique column (order_id)"),
        ("SELECT email, COUNT(*) AS n FROM self GROUP BY email", "personal-data columns (email)"),
    ],
)
def test_results_that_would_leak_rows_or_personal_data_stay_local(sql, reason):
    decision = decide(sql)
    assert not decision.allowed and reason in decision.reason


def test_masked_personal_columns_are_fine():
    assert decide("SELECT phone, COUNT(*) AS n FROM self GROUP BY phone").allowed


def test_large_aggregates_stay_local():
    big = {**SMALL, "row_count": 25}
    decision = decide("SELECT region, COUNT(*) AS n FROM self GROUP BY region", result=big)
    assert not decision.allowed and "more than 20 rows" in decision.reason


def test_local_summary_for_a_single_value():
    assert local_summary({"columns": ["total"], "rows": [[1234567]], "row_count": 1, "truncated": False}) == (
        "**total**: 1,234,567"
    )


def test_local_summary_names_highest_and_lowest():
    assert local_summary(SMALL) == "2 rows. Highest total: **South** (30). Lowest: **North** (10)."


def test_local_summary_without_numbers_or_rows():
    text_only = {"columns": ["region"], "rows": [["North"], ["South"]], "row_count": 2, "truncated": True}
    assert local_summary(text_only) == "2 rows (showing the first ones)."
    assert local_summary({**SMALL, "rows": [], "row_count": 0}) == "The query returned no rows."


def test_local_summary_keeps_ids_as_plain_labels():
    rows = {
        "columns": ["order_id", "revenue"],
        "rows": [[1105, 4500], [1007, 3600]],
        "row_count": 2,
        "truncated": False,
    }
    assert local_summary(rows) == "2 rows. Highest revenue: **1105** (4,500). Lowest: **1007** (3,600)."

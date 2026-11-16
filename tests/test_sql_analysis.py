import pytest

from csv_intelligence.sql.analysis import (
    group_by_columns,
    referenced_columns,
    returns_only_aggregates,
    string_filters,
)
from csv_intelligence.sql.guard import parse_select


def test_string_filters_from_equality_and_in():
    tree = parse_select(
        "SELECT * FROM self "
        "WHERE region = 'south' AND 'Desk' = product AND category IN ('a', 'b') AND units = 3"
    )
    assert string_filters(tree) == [
        ("region", "south"),
        ("product", "Desk"),
        ("category", "a"),
        ("category", "b"),
    ]


def test_string_filters_ignore_wrapped_columns():
    assert string_filters(parse_select("SELECT * FROM self WHERE LOWER(region) = 'south'")) == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM self",
        "SELECT region, SUM(revenue) AS total FROM self GROUP BY region",
        "WITH t AS (SELECT region, SUM(revenue) AS r FROM self GROUP BY region) SELECT * FROM t ORDER BY r",
        "SELECT region FROM self GROUP BY region "
        "UNION ALL SELECT category AS region FROM self GROUP BY category",
    ],
)
def test_aggregated_queries(sql):
    assert returns_only_aggregates(parse_select(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM self",
        "SELECT DISTINCT region FROM self",
        "SELECT revenue, SUM(revenue) OVER () AS total FROM self",
        "SELECT region, COUNT(*) AS n FROM self GROUP BY region UNION ALL SELECT region, revenue FROM self",
        "WITH t AS (SELECT * FROM self) SELECT region, SUM(revenue) AS r FROM t GROUP BY region",
        "SELECT order_id, COUNT(*) AS n FROM self",
    ],
)
def test_row_level_queries(sql):
    assert not returns_only_aggregates(parse_select(sql))


def test_referenced_and_group_by_columns():
    tree = parse_select("SELECT region, SUM(revenue) AS r FROM self WHERE units > 1 GROUP BY region")
    assert referenced_columns(tree) == {"region", "revenue", "units"}
    assert group_by_columns(tree) == {"region"}

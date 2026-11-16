import pytest

from csv_intelligence.sql.filters import closest_value, replace_string_literals

STORED = ["North", "South", "Pen Set", "Laptop"]


@pytest.mark.parametrize(
    "requested, expected",
    [
        ("South", "South"),
        ("south", "South"),
        ("  SOUTH ", "South"),
        ("pen set", "Pen Set"),
        ("Laptops", "Laptop"),
        ("Atlantis", None),
    ],
)
def test_closest_value(requested, expected):
    assert closest_value(requested, STORED) == expected


def test_replace_string_literals_keeps_everything_else_untouched():
    sql = "SELECT region AS \"south\" FROM self WHERE region = 'south' AND note = 'it''s'  -- 'south'"
    assert replace_string_literals(sql, {"south": "South", "it's": "It's"}) == (
        "SELECT region AS \"south\" FROM self WHERE region = 'South' AND note = 'It''s'  -- 'south'"
    )


def test_replace_string_literals_without_replacements_is_identity():
    assert replace_string_literals("SELECT 'x' AS y", {}) == "SELECT 'x' AS y"

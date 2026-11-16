import pytest

from csv_intelligence.sql.guard import UnsafeQueryError, parse_select


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT region, SUM(revenue) AS total FROM self GROUP BY region",
        "WITH t AS (SELECT strftime(order_date, '%Y-%m') AS m FROM self) SELECT * FROM t",
        "SELECT a FROM self UNION ALL SELECT b AS a FROM self",
        "SELECT date_part('month', order_date) AS m, COUNT(*) AS n FROM self GROUP BY 1",
        'SELECT "unit price" FROM self',
        "SELECT region FROM self;",
    ],
)
def test_read_only_selects_are_allowed(sql):
    parse_select(sql)


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("DROP TABLE self", "Only SELECT"),
        ("CREATE TABLE x AS SELECT * FROM self", "Only SELECT"),
        ("SHOW TABLES", "Only SELECT"),
        ("DELETE FROM self", "Only SELECT"),
        ("SELECT 1; SELECT 2", "exactly one"),
        ("SELECT * INTO copy FROM self", "INTO"),
        ("SELECT * FROM self WHERE", "Could not parse"),
    ],
)
def test_writes_and_odd_statements_are_rejected(sql, reason):
    with pytest.raises(UnsafeQueryError, match=reason):
        parse_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('../secret.parquet')",
        "SELECT * FROM 'other.csv'",
        "SELECT * FROM other_table",
        "SELECT * FROM main.self",
    ],
)
def test_only_the_dataset_table_can_be_read(sql):
    with pytest.raises(UnsafeQueryError, match="only read the table"):
        parse_select(sql)


def test_file_reading_functions_are_rejected_anywhere():
    with pytest.raises(UnsafeQueryError, match="File-reading function"):
        parse_select("SELECT read_csv('/etc/passwd') AS x FROM self")


def test_warm_up_parses_a_query_once():
    from csv_intelligence.sql.guard import warm_up

    warm_up()  # must not raise; it only loads the dialect ahead of the first real question

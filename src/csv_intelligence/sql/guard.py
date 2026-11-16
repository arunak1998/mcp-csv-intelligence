"""Accept only a single read-only SELECT on the dataset table; reject everything else before it runs."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Polars SQL is close to DuckDB's dialect (double-quoted identifiers, strftime, date_part, ...).
DIALECT = "duckdb"
TABLE = "self"

WRITE_OR_ADMIN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Into,
    exp.Command,
    exp.Pragma,
    exp.Set,
    exp.Use,
)


class UnsafeQueryError(ValueError):
    """The SQL was rejected before execution."""


def _parse_one(sql: str) -> exp.Expression:
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=DIALECT) if statement is not None]
    except SqlglotError as error:
        raise UnsafeQueryError(f"Could not parse the SQL: {error}") from error
    if len(statements) != 1:
        raise UnsafeQueryError(f"Send exactly one SQL statement (got {len(statements)}).")
    return statements[0]


def _check_tables(tree: exp.Expression) -> None:
    """Only `self` and the query's own CTEs may be read; table functions like read_csv(...) cannot."""
    allowed = {TABLE} | {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        is_plain_name = isinstance(table.this, exp.Identifier) and not table.args.get("db")
        if not is_plain_name or table.name not in allowed:
            raise UnsafeQueryError(f"Queries may only read the table `{TABLE}` (found `{table.sql()}`).")


def _check_functions(tree: exp.Expression) -> None:
    for function in tree.find_all(exp.Func):
        name = (function.name if isinstance(function, exp.Anonymous) else function.sql_name()).lower()
        if name.startswith(("read_", "scan_")):
            raise UnsafeQueryError(f"File-reading function `{name}` is not allowed.")


def parse_select(sql: str) -> exp.Query:
    """Return the parsed query, or raise UnsafeQueryError if it is anything but one read-only SELECT."""
    tree = _parse_one(sql)
    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("Only SELECT queries are allowed.")
    forbidden = tree.find(*WRITE_OR_ADMIN)
    if forbidden is not None:
        raise UnsafeQueryError(f"`{forbidden.key.upper()}` is not allowed; queries must be read-only.")
    _check_tables(tree)
    _check_functions(tree)
    return tree


def warm_up() -> None:
    """Parse once at startup: sqlglot loads its dialect on first use (~0.1 s), not on the first question."""
    parse_select(f"SELECT 1 AS warm_up FROM {TABLE}")

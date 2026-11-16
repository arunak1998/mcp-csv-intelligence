"""MCP server: lists datasets, returns their cached profile and runs Polars SQL on the Parquet file."""

import asyncio
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import polars as pl
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from csv_intelligence.data import datasets
from csv_intelligence.data.profile import load_profile
from csv_intelligence.server.sql_reference import describe_sql_functions
from csv_intelligence.settings import load_settings
from csv_intelligence.sql.analysis import string_filters
from csv_intelligence.sql.filters import closest_value, replace_string_literals
from csv_intelligence.sql.guard import parse_select, warm_up
from csv_intelligence.timing import Timer

_startup = load_settings()
mcp = FastMCP("analyst", host=_startup.mcp_host, port=_startup.mcp_port)

QUERY_DESCRIPTION = f"""
One Polars SQL SELECT query. Use `self` as the table name.
Supported functions are:
{describe_sql_functions()}
"""


def upload_dir() -> Path:
    return load_settings().upload_dir


def to_json_value(value: Any) -> Any:
    """Convert values Polars returns into JSON-friendly ones."""
    if isinstance(value, date | datetime | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, timedelta):
        return str(value)
    return value


# Text columns with more distinct values than this are not matched (they are rarely filtered by equality).
MAX_DISTINCT_FOR_MATCHING = 50_000
TEXT_TYPES = (pl.String, pl.Categorical, pl.Enum)


class QueryTimeoutError(TimeoutError):
    """The query ran longer than QUERY_TIMEOUT_SECONDS."""


def query_parquet(path: Path, query: str, max_rows: int) -> dict[str, Any]:
    """Run query lazily on the Parquet file and return at most max_rows rows."""
    frame = pl.scan_parquet(path).sql(query).limit(max_rows + 1).collect()
    truncated = frame.height > max_rows
    frame = frame.head(max_rows)
    return {
        "columns": frame.columns,
        "rows": [[to_json_value(value) for value in row] for row in frame.iter_rows()],
        "row_count": frame.height,
        "truncated": truncated,
    }


def distinct_text_values(path: Path, column: str) -> list[str] | None:
    """Distinct values of a text column, or None when there are too many to match against."""
    values = (
        pl.scan_parquet(path)
        .select(pl.col(column).cast(pl.String).drop_nulls().unique())
        .head(MAX_DISTINCT_FOR_MATCHING + 1)
        .collect()
        .to_series()
        .to_list()
    )
    return values if len(values) <= MAX_DISTINCT_FOR_MATCHING else None


def match_filter_values(path: Path, query: str) -> list[dict[str, Any]]:
    """Match each `text_column = 'value'` in the query to a value that really exists in that column.

    Returns one entry per value that was changed ('south' -> 'South') or not found (matched: None).
    This runs here, next to the data; the LLM never sees the column's values.
    """
    text_columns = {
        name
        for name, dtype in pl.scan_parquet(path).collect_schema().items()
        if isinstance(dtype, TEXT_TYPES)
    }
    matches = []
    for column, requested in dict.fromkeys(string_filters(parse_select(query))):
        stored = distinct_text_values(path, column) if column in text_columns else None
        if stored is None:
            continue
        matched = closest_value(requested, stored)
        if matched != requested:
            matches.append({"column": column, "requested": requested, "matched": matched})
    return matches


def answer_query(path: Path, query: str, max_rows: int, timer: Timer) -> dict[str, Any]:
    """Fix filter values to match the data, then run the query. Returns the SQL that actually ran."""
    with timer.step("match_filters"):
        matches = match_filter_values(path, query)
        final_sql = replace_string_literals(
            query, {match["requested"]: match["matched"] for match in matches if match["matched"]}
        )
        if final_sql != query:
            parse_select(final_sql)
    with timer.step("query"):
        result = query_parquet(path, final_sql, max_rows)
    return {**result, "sql": final_sql, "filter_matches": matches}


@mcp.tool()
def list_datasets() -> dict[str, list[str]]:
    """List the datasets that can be queried."""
    return {"datasets": datasets.list_datasets(upload_dir())}


@mcp.tool()
def get_schema(dataset: str) -> dict[str, Any]:
    """Column names, types and summary statistics of a dataset. No rows are returned."""
    return load_profile(datasets.resolve_inside_uploads(upload_dir(), dataset, ".profile.json"))


@mcp.tool()
async def run_sql(
    dataset: str,
    query: Annotated[str, Field(description=QUERY_DESCRIPTION)],
) -> dict[str, Any]:
    """Run one read-only Polars SQL query on a dataset and return columns and rows.

    The query is checked before it runs: one SELECT statement, reading only `self`.
    Text filter values are matched to the stored spelling ('south' -> 'South'); the response's
    `sql` is the query that actually ran and `filter_matches` lists what was changed.
    Results are capped at MAX_RESULT_ROWS and the query is stopped after QUERY_TIMEOUT_SECONDS.
    `timings_ms` reports check_sql, match_filters and query.
    """
    settings, timer = load_settings(), Timer()
    path = datasets.resolve_inside_uploads(settings.upload_dir, dataset, ".parquet")
    with timer.step("check_sql"):
        parse_select(query)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(answer_query, path, query, settings.max_result_rows, timer),
            timeout=settings.query_timeout_seconds,
        )
    except TimeoutError as error:
        raise QueryTimeoutError(
            f"The query took longer than {settings.query_timeout_seconds:g}s and was stopped"
        ) from error
    return {**result, "timings_ms": timer.ms}


def main() -> None:
    # stdout carries the MCP protocol, so diagnostics go to stderr
    print(
        f"[server] listening on {_startup.mcp_host}:{_startup.mcp_port} (datasets: {_startup.upload_dir})",
        file=sys.stderr,
        flush=True,
    )
    warm_up()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

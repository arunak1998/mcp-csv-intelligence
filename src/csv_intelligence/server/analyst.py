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
from csv_intelligence.sql.guard import parse_select

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
    Results are capped at MAX_RESULT_ROWS and the query is stopped after QUERY_TIMEOUT_SECONDS.
    """
    settings = load_settings()
    path = datasets.resolve_inside_uploads(settings.upload_dir, dataset, ".parquet")
    parse_select(query)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(query_parquet, path, query, settings.max_result_rows),
            timeout=settings.query_timeout_seconds,
        )
    except TimeoutError as error:
        raise QueryTimeoutError(
            f"The query took longer than {settings.query_timeout_seconds:g}s and was stopped"
        ) from error


def main() -> None:
    # stdout carries the MCP protocol, so diagnostics go to stderr
    print(
        f"[server] listening on {_startup.mcp_host}:{_startup.mcp_port} (datasets: {_startup.upload_dir})",
        file=sys.stderr,
        flush=True,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

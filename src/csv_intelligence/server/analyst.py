"""MCP server exposing CSV discovery, schema inspection and Polars SQL execution."""

import os
import sys
from glob import glob
from typing import Annotated, Any

import polars as pl
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from csv_intelligence.server.sql_reference import describe_sql_functions

load_dotenv()

FILE_LOCATION = os.getenv("FILE_LOCATION", "data/uploads/*.csv")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8050"))

mcp = FastMCP("analyst", host=MCP_HOST, port=MCP_PORT)

QUERY_DESCRIPTION = f"""
The polars sql query to be executed.
polars sql query must use the table name as `self` to refer to the source data.
Supported functions are:
{describe_sql_functions()}
"""


def read_file(file_location: str, file_type: str = "csv") -> pl.DataFrame:
    if file_type == "csv":
        return pl.read_csv(file_location)
    if file_type == "parquet":
        return pl.read_parquet(file_location)
    raise ValueError(f"Unsupported file type: {file_type}")


def read_file_list(file_locations: list[str], file_type: str = "csv") -> pl.DataFrame:
    """Read several same-schema files into one DataFrame (CSV is scanned lazily)."""
    if file_type == "csv":
        return pl.concat([pl.scan_csv(f) for f in file_locations]).collect()
    if file_type == "parquet":
        return pl.read_parquet(file_locations)
    raise ValueError(f"Unsupported file type: {file_type}")


@mcp.tool(name="get_files_list", description="Get list of source CSV files")
def get_files_list() -> list[str]:
    return glob(FILE_LOCATION)


@mcp.tool()
def get_schema(file_location: str, file_type: str = "csv") -> list[dict[str, Any]]:
    """Return the column names and data types of a file."""
    df = read_file(file_location, file_type)
    return [{"name": col, "dtype": str(dtype)} for col, dtype in df.schema.items()]


@mcp.tool()
def execute_polars_sql(
    file_locations: list[str],
    query: Annotated[str, Field(description=QUERY_DESCRIPTION)],
    file_type: Annotated[
        str,
        Field(description="The type of the file to be read. Supported types are csv and parquet"),
    ] = "csv",
) -> list[dict[str, Any]]:
    """
    Reads the data from the given file locations. Note that file_locations
    can be a list of multiple files. However, all files must have the same schema
    and the same columns. Executes the given polars sql query and returns the result.
    Note that the polars sql query must use the table name as `self` to refer to the source data.
    """
    df = read_file_list(file_locations, file_type)
    return df.sql(query).to_dicts()


def main() -> None:
    # stdout carries the MCP protocol, so diagnostics go to stderr
    print(
        f"[server] listening on {MCP_HOST}:{MCP_PORT} (files: {FILE_LOCATION})", file=sys.stderr, flush=True
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

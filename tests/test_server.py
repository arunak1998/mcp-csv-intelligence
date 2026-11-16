import json
import time

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from csv_intelligence.data.datasets import DatasetNotFoundError
from csv_intelligence.server import analyst
from csv_intelligence.sql.guard import UnsafeQueryError


async def call(tool: str, arguments: dict):
    """Call a tool through FastMCP's registry, as a real MCP client would."""
    content, _ = await analyst.mcp.call_tool(tool, arguments)
    return json.loads(content[0].text)


async def test_tools_are_registered():
    names = {tool.name for tool in await analyst.mcp.list_tools()}
    assert names == {"list_datasets", "get_schema", "run_sql"}


async def test_sql_tool_advertises_supported_functions():
    tool = next(t for t in await analyst.mcp.list_tools() if t.name == "run_sql")
    assert "Aggregate" in tool.inputSchema["properties"]["query"]["description"]


def test_list_datasets(sales_dataset):
    assert analyst.list_datasets() == {"datasets": ["sample_sales"]}


def test_list_datasets_when_empty(upload_dir):
    assert analyst.list_datasets() == {"datasets": []}


def test_get_schema_returns_cached_profile(sales_dataset):
    profile = analyst.get_schema(sales_dataset)
    types = {column["name"]: column["dtype"] for column in profile["columns"]}
    assert types["region"] == "String"
    assert types["order_date"] == "Date"
    assert profile["row_count"] == 120


async def test_run_sql_aggregates(sales_dataset):
    result = await analyst.run_sql(
        sales_dataset, "SELECT region, SUM(revenue) AS total FROM self GROUP BY region ORDER BY region"
    )
    assert result["columns"] == ["region", "total"]
    assert [row[0] for row in result["rows"]] == ["East", "North", "South", "West"]
    assert result["truncated"] is False


async def test_run_sql_returns_dates_as_text(sales_dataset):
    result = await analyst.run_sql(sales_dataset, "SELECT MIN(order_date) AS first FROM self")
    assert isinstance(result["rows"][0][0], str)


async def test_run_sql_caps_rows(sales_dataset, monkeypatch):
    monkeypatch.setenv("MAX_RESULT_ROWS", "5")
    result = await analyst.run_sql(sales_dataset, "SELECT order_id FROM self")
    assert result["row_count"] == 5
    assert result["truncated"] is True


async def test_run_sql_through_mcp_registry(sales_dataset):
    result = await call("run_sql", {"dataset": sales_dataset, "query": "SELECT COUNT(*) AS n FROM self"})
    assert result["rows"] == [[120]]


@pytest.mark.parametrize("name", ["../sample_sales", "/etc/passwd", "sample_sales/../../x", "missing"])
async def test_run_sql_refuses_names_outside_the_upload_folder(sales_dataset, name):
    with pytest.raises(DatasetNotFoundError):
        await analyst.run_sql(name, "SELECT 1 AS x FROM self")


def test_get_schema_refuses_names_outside_the_upload_folder(sales_dataset):
    with pytest.raises(DatasetNotFoundError):
        analyst.get_schema("../sample_sales")


@pytest.mark.parametrize(
    "query",
    ["DROP TABLE self", "SELECT * FROM read_csv('/etc/passwd')", "SELECT 1 AS a; SELECT 2 AS b"],
)
async def test_run_sql_rejects_unsafe_queries_before_running_them(sales_dataset, query, monkeypatch):
    monkeypatch.setattr(analyst, "query_parquet", lambda *args: pytest.fail("query should not run"))
    with pytest.raises(UnsafeQueryError):
        await analyst.run_sql(sales_dataset, query)


async def test_run_sql_stops_slow_queries(sales_dataset, monkeypatch):
    monkeypatch.setenv("QUERY_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(analyst, "query_parquet", lambda *args: time.sleep(0.5))
    with pytest.raises(analyst.QueryTimeoutError, match="longer than 0.05s"):
        await analyst.run_sql(sales_dataset, "SELECT COUNT(*) AS n FROM self")


async def test_unsafe_query_through_mcp_registry_is_reported_as_a_tool_error(sales_dataset):
    with pytest.raises(ToolError, match="Only SELECT"):
        await analyst.mcp.call_tool("run_sql", {"dataset": sales_dataset, "query": "DROP TABLE self"})


async def test_run_sql_matches_filter_values_to_the_stored_spelling(sales_dataset):
    result = await analyst.run_sql(
        sales_dataset,
        "SELECT COUNT(*) AS n FROM self WHERE region = 'south' AND product IN ('laptops', 'Atlantis')",
    )
    assert result["sql"] == (
        "SELECT COUNT(*) AS n FROM self WHERE region = 'South' AND product IN ('Laptop', 'Atlantis')"
    )
    assert result["filter_matches"] == [
        {"column": "region", "requested": "south", "matched": "South"},
        {"column": "product", "requested": "laptops", "matched": "Laptop"},
        {"column": "product", "requested": "Atlantis", "matched": None},
    ]
    assert result["rows"][0][0] > 0


async def test_run_sql_leaves_exact_filters_alone(sales_dataset):
    query = "SELECT COUNT(*) AS n FROM self WHERE region = 'South'"
    result = await analyst.run_sql(sales_dataset, query)
    assert result["sql"] == query
    assert result["filter_matches"] == []


async def test_run_sql_reports_its_own_steps(sales_dataset):
    result = await analyst.run_sql(sales_dataset, "SELECT COUNT(*) AS n FROM self WHERE region = 'south'")
    assert list(result["timings_ms"]) == ["check_sql", "match_filters", "query"]
    assert all(isinstance(ms, int) and ms >= 0 for ms in result["timings_ms"].values())

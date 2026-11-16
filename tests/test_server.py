import json

from csv_intelligence.server import analyst


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


def test_run_sql_aggregates(sales_dataset):
    result = analyst.run_sql(
        sales_dataset, "SELECT region, SUM(revenue) AS total FROM self GROUP BY region ORDER BY region"
    )
    assert result["columns"] == ["region", "total"]
    assert [row[0] for row in result["rows"]] == ["East", "North", "South", "West"]
    assert result["truncated"] is False


def test_run_sql_returns_dates_as_text(sales_dataset):
    result = analyst.run_sql(sales_dataset, "SELECT MIN(order_date) AS first FROM self")
    assert isinstance(result["rows"][0][0], str)


def test_run_sql_caps_rows(sales_dataset, monkeypatch):
    monkeypatch.setenv("MAX_RESULT_ROWS", "5")
    result = analyst.run_sql(sales_dataset, "SELECT order_id FROM self")
    assert result["row_count"] == 5
    assert result["truncated"] is True


async def test_run_sql_through_mcp_registry(sales_dataset):
    result = await call("run_sql", {"dataset": sales_dataset, "query": "SELECT COUNT(*) AS n FROM self"})
    assert result["rows"] == [[120]]

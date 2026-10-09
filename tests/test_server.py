import json

import pytest

from csv_intelligence.server import analyst

SAMPLE = "data/sample_sales.csv"


async def call(tool: str, arguments: dict):
    """Call a tool through FastMCP's registry, as a real MCP client would."""
    content, _ = await analyst.mcp.call_tool(tool, arguments)
    return [json.loads(block.text) if block.text.startswith(("{", "[")) else block.text for block in content]


async def test_all_three_tools_are_registered():
    names = {tool.name for tool in await analyst.mcp.list_tools()}
    assert names == {"get_files_list", "get_schema", "execute_polars_sql"}


async def test_sql_tool_advertises_supported_functions():
    tool = next(t for t in await analyst.mcp.list_tools() if t.name == "execute_polars_sql")
    assert "Aggregate" in tool.inputSchema["properties"]["query"]["description"]


def test_get_files_list_uses_file_location(tmp_path, monkeypatch):
    (tmp_path / "one.csv").write_text("a\n1\n")
    (tmp_path / "ignored.txt").write_text("x")
    monkeypatch.setattr(analyst, "FILE_LOCATION", str(tmp_path / "*.csv"))
    assert analyst.get_files_list() == [str(tmp_path / "one.csv")]


def test_get_schema_reports_columns_and_types():
    schema = {column["name"]: column["dtype"] for column in analyst.get_schema(SAMPLE)}
    assert schema["region"] == "String"
    assert schema["revenue"] == "Int64"


def test_execute_polars_sql_aggregates():
    rows = analyst.execute_polars_sql(
        [SAMPLE], "SELECT region, SUM(revenue) AS total FROM self GROUP BY region ORDER BY region"
    )
    assert [row["region"] for row in rows] == ["East", "North", "South", "West"]
    assert all(row["total"] > 0 for row in rows)


def test_execute_polars_sql_concatenates_files_with_same_schema(tmp_path):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("n\n1\n2\n")
    rows = analyst.execute_polars_sql(
        [str(tmp_path / "a.csv"), str(tmp_path / "b.csv")], "SELECT COUNT(*) AS rows FROM self"
    )
    assert rows == [{"rows": 4}]


def test_unsupported_file_type_is_rejected():
    with pytest.raises(ValueError, match="Unsupported file type"):
        analyst.read_file(SAMPLE, "xlsx")


async def test_get_schema_through_mcp_registry():
    result = await call("get_schema", {"file_location": SAMPLE})
    assert any(item["name"] == "order_id" for item in result)

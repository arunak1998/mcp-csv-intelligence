import json

import pytest

from csv_intelligence.agents import dashboard_agent
from csv_intelligence.agents.csv_agent import context_hook
from csv_intelligence.agents.data_context import load_data_context
from csv_intelligence.agents.parsing import DataContext

SCHEMA_RESULT = [
    json.dumps({"name": "region", "dtype": "String"}),
    json.dumps({"name": "revenue", "dtype": "Int64"}),
]


async def test_load_data_context_reads_first_file_and_schema(fake_tool):
    schema_tool = fake_tool("get_schema", SCHEMA_RESULT)
    tools = [fake_tool("get_files_list", "data/a.csv"), schema_tool]

    context = await load_data_context(tools)

    assert context == DataContext("data/a.csv", {"region": "String", "revenue": "Int64"})
    assert schema_tool.calls == [{"file_location": "data/a.csv"}]


async def test_load_data_context_without_files_is_empty(fake_tool):
    context = await load_data_context([fake_tool("get_files_list", []), fake_tool("get_schema", [])])
    assert context == DataContext("", {})


def test_context_hook_prepends_file_and_columns():
    hook = context_hook(DataContext("data/a.csv", {"region": "String", "revenue": "Int64"}))
    result = hook({"messages": ["question"]})

    system, original = result["llm_input_messages"]
    assert "data/a.csv" in system.content and "region, revenue" in system.content
    assert original == "question"


async def test_plan_metrics_parses_fenced_json(fake_llm):
    plan = {"key_metrics": [{"metric": "Revenue", "sql": "SELECT 1"}]}
    llm = fake_llm(f"```json\n{json.dumps(plan)}\n```")

    metrics = await dashboard_agent.plan_metrics(llm, DataContext("a.csv", {"x": "Int64"}), "revenue?")

    assert metrics == plan["key_metrics"]
    sent = json.loads(llm.received[0][1].content)
    assert sent == {"schema": [{"name": "x", "dtype": "Int64"}], "question": "revenue?"}


async def test_plan_metrics_rejects_empty_plan(fake_llm):
    with pytest.raises(ValueError, match="key_metrics"):
        await dashboard_agent.plan_metrics(fake_llm('{"key_metrics": []}'), DataContext("a.csv", {}), "q")


METRIC = {"metric": "Revenue", "description": "d", "visualization_type": "bar_chart", "sql": "SELECT 1"}


async def test_run_metric_queries_skips_failing_metrics(fake_tool):
    failing = fake_tool("execute_polars_sql", error=RuntimeError("bad sql"))
    with pytest.raises(RuntimeError, match="None of the generated SQL"):
        await dashboard_agent.run_metric_queries([failing], [METRIC], "a.csv")


async def test_run_metric_queries_skips_error_text_but_keeps_good_metrics(fake_tool):
    class MixedTool(fake_tool):
        async def ainvoke(self, arguments):
            if "nope" in arguments["query"]:
                return "Error executing tool execute_polars_sql: unable to find column"
            return [{"type": "text", "text": '{"n": 120}'}]

    tool = MixedTool("execute_polars_sql")
    bad = {**METRIC, "metric": "Bad", "sql": "SELECT nope FROM self"}

    results = await dashboard_agent.run_metric_queries([tool], [bad, METRIC], "a.csv")

    assert [r["metric"] for r in results] == ["Revenue"]
    assert results[0]["data"] == [{"n": 120}]


async def test_run_metric_queries_returns_rows(fake_tool):
    tool = fake_tool("execute_polars_sql", [{"total": 5}])

    results = await dashboard_agent.run_metric_queries([tool], [METRIC], "a.csv")

    assert results[0]["data"] == [{"total": 5}]
    assert tool.calls == [{"file_locations": ["a.csv"], "query": "SELECT 1", "file_type": "csv"}]


async def test_render_dashboard_strips_code_fence(fake_llm):
    html = await dashboard_agent.render_dashboard(fake_llm("```html\n<html></html>\n```"), [])
    assert html == "<html></html>"

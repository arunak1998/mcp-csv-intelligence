import asyncio
import json

import pytest

from conftest import InProcessMcp
from csv_intelligence.agents import dashboard_agent
from csv_intelligence.agents.dataset import NO_DATASET_MESSAGE

PLAN = {
    "title": "Sales overview",
    "metrics": [
        {
            "title": "Revenue",
            "description": "Total",
            "chart": "kpi",
            "sql": "SELECT SUM(revenue) AS r FROM self",
        },
        {
            "title": "By region",
            "chart": "bar",
            "sql": "SELECT region, SUM(revenue) AS r FROM self GROUP BY region ORDER BY r DESC",
        },
        {"title": "Broken", "chart": "line", "sql": "SELECT nope FROM self"},
        {"title": "No SQL", "chart": "bar"},
        {"title": "Odd chart", "chart": "radar", "sql": "SELECT COUNT(*) AS n FROM self"},
    ],
}


async def test_dashboard_plans_once_and_builds_the_spec_locally(mcp, fake_llm):
    llm = fake_llm(json.dumps(PLAN))

    dashboard = await dashboard_agent.build_dashboard("Sales dashboard", mcp, llm)

    spec = dashboard["spec"]
    assert spec["title"] == "Sales overview"
    assert [panel["chart"] for panel in spec["panels"]] == ["kpi", "bar", "table"]  # radar -> table
    assert spec["panels"][0]["value"] == "163,107"
    assert spec["skipped"][0]["title"] == "Broken" and "nope" in spec["skipped"][0]["reason"]
    assert len(llm.received) == 1  # one planning call; results never go back to the LLM
    assert [call["step"] for call in dashboard["audit"]] == ["plan_dashboard"]
    assert set(dashboard["timings_ms"]) == {"plan", "queries"}


async def test_the_plan_prompt_has_the_schema_but_no_values(mcp, fake_llm):
    dashboard = await dashboard_agent.build_dashboard("Sales", mcp, fake_llm(json.dumps(PLAN)))
    sent = dashboard["audit"][0]["user"]
    assert "North" not in sent and "Laptop" not in sent and json.loads(sent)["question"] == "Sales"


async def test_metric_queries_run_concurrently(sales_dataset):
    class SlowMcp(InProcessMcp):
        running = peak = 0

        async def call(self, tool, arguments=None):
            SlowMcp.running += 1
            SlowMcp.peak = max(SlowMcp.peak, SlowMcp.running)
            await asyncio.sleep(0.05)
            SlowMcp.running -= 1
            return await super().call(tool, arguments)

    metrics = [{"title": str(i), "chart": "kpi", "sql": "SELECT COUNT(*) AS n FROM self"} for i in range(5)]
    results = await dashboard_agent.run_metrics(SlowMcp(), sales_dataset, metrics)

    assert SlowMcp.peak == 5
    assert all(result["result"]["rows"] == [[120]] for result in results)


async def test_plan_without_usable_metrics_is_an_error(mcp, fake_llm):
    with pytest.raises(ValueError, match="without metrics"):
        await dashboard_agent.build_dashboard("x", mcp, fake_llm('{"metrics": [{"title": "no sql"}]}'))


async def test_dashboard_when_every_query_fails(mcp, fake_llm):
    plan = {"metrics": [{"title": "Bad", "chart": "kpi", "sql": "SELECT nope FROM self"}]}
    with pytest.raises(RuntimeError, match="None of the planned queries"):
        await dashboard_agent.build_dashboard("x", mcp, fake_llm(json.dumps(plan)))


async def test_dashboard_without_a_dataset(upload_dir, fake_llm):
    with pytest.raises(ValueError, match=NO_DATASET_MESSAGE):
        await dashboard_agent.build_dashboard("x", InProcessMcp(), fake_llm())

"""Dashboard: plan metrics from the schema (one LLM call), run their SQL in parallel, build a chart spec.

The query results never go back to the LLM: the spec is built locally and rendered by a template.
"""

import asyncio
import logging
import time
from typing import Any

from langchain_core.language_models import BaseChatModel

from csv_intelligence.agents.audit import LlmAudit
from csv_intelligence.agents.dataset import NO_DATASET_MESSAGE, active_dataset
from csv_intelligence.agents.mcp_client import McpClient, ToolCallError
from csv_intelligence.agents.parsing import message_text, parse_json_object
from csv_intelligence.agents.privacy import schema_for_llm
from csv_intelligence.agents.prompts import PLAN_DASHBOARD_PROMPT
from csv_intelligence.dashboards.spec import CHART_TYPES, build_spec
from csv_intelligence.timing import Timer, elapsed_ms

logger = logging.getLogger(__name__)

MAX_METRICS = 6


def valid_metrics(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Metrics that have SQL, with an unknown chart type falling back to a table."""
    metrics = []
    for metric in plan.get("metrics") or []:
        if isinstance(metric, dict) and isinstance(metric.get("sql"), str) and metric["sql"].strip():
            chart = metric.get("chart") if metric.get("chart") in CHART_TYPES else "table"
            metrics.append({**metric, "chart": chart})
    return metrics[:MAX_METRICS]


async def plan_metrics(
    llm: BaseChatModel, audit: LlmAudit, question: str, schema: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    """Ask the LLM for a title and metrics (each with SQL and a chart type) from the schema only."""
    messages = audit.messages(
        "plan_dashboard", PLAN_DASHBOARD_PROMPT, {"question": question, "schema": schema}
    )
    plan = parse_json_object(message_text((await llm.ainvoke(messages)).content))
    metrics = valid_metrics(plan)
    if not metrics:
        raise ValueError("The model returned a plan without metrics")
    return plan.get("title") or "Dashboard", metrics


async def run_metric(mcp: McpClient, dataset: str, metric: dict[str, Any]) -> dict[str, Any]:
    """Run one metric's SQL; a failure is recorded on the metric instead of failing the dashboard.

    "ms" is the metric's own round trip, so a slow query stands out even though all run at once.
    """
    start = time.perf_counter()
    try:
        result = await mcp.call("run_sql", {"dataset": dataset, "query": metric["sql"]})
        return {**metric, "result": result, "ms": elapsed_ms(start)}
    except ToolCallError as error:
        logger.warning("Metric %r failed: %s", metric.get("title"), error)
        return {**metric, "error": str(error), "ms": elapsed_ms(start)}


async def run_metrics(mcp: McpClient, dataset: str, metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All metric queries at once over the shared MCP session."""
    return list(await asyncio.gather(*(run_metric(mcp, dataset, metric) for metric in metrics)))


def metric_timings(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"title": result.get("title") or "Metric", "ms": result["ms"], "ok": "result" in result}
        for result in results
    ]


async def build_dashboard(
    question: str, mcp: McpClient, llm: BaseChatModel, timer: Timer | None = None
) -> dict[str, Any]:
    """Return {"spec", "audit", "timings_ms", "metric_timings"} for the active dataset.

    timings_ms: load_dataset, plan (LLM), queries (all metrics, in parallel), build_spec, total.
    Pass a timer to add later steps (such as rendering) to the same report.
    """
    audit, timer = LlmAudit(), timer or Timer()
    with timer.step("load_dataset"):
        dataset = await active_dataset(mcp)
    if dataset is None:
        raise ValueError(NO_DATASET_MESSAGE)
    name, profile = dataset

    with timer.step("plan"):
        title, metrics = await plan_metrics(llm, audit, question, schema_for_llm(profile))
    with timer.step("queries"):
        results = await run_metrics(mcp, name, metrics)
    with timer.step("build_spec"):
        spec = build_spec(title, question, results)
    if not spec["panels"]:
        raise RuntimeError("None of the planned queries could be run")
    return {
        "spec": spec,
        "audit": audit.calls,
        "timings_ms": timer.report(),
        "metric_timings": metric_timings(results),
    }

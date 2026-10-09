"""Dashboard pipeline: plan metrics from the schema, run their SQL, render an HTML dashboard."""

import json
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from csv_intelligence.agents.connection import McpConnection, find_tool, open_mcp_tools
from csv_intelligence.agents.data_context import load_data_context
from csv_intelligence.agents.llm import create_llm
from csv_intelligence.agents.parsing import DataContext, parse_json_object, parse_rows, strip_code_fence
from csv_intelligence.agents.prompts import RENDER_DASHBOARD_PROMPT, SCHEMA_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


async def plan_metrics(llm: BaseChatModel, data: DataContext, question: str) -> list[dict]:
    """Ask the LLM for the key metrics (each with a Polars SQL query) that answer the question."""
    payload = {"schema": data.schema_as_list(), "question": question}
    response = await llm.ainvoke(
        [SystemMessage(content=SCHEMA_ANALYSIS_PROMPT), HumanMessage(content=json.dumps(payload))]
    )
    plan = parse_json_object(response.content)
    if not plan.get("key_metrics"):
        raise ValueError("The model returned a plan without key_metrics")
    return plan["key_metrics"]


async def run_metric_queries(tools: list[BaseTool], metrics: list[dict], file_path: str) -> list[dict]:
    """Execute each metric's SQL; a metric whose query fails is skipped rather than failing the dashboard."""
    execute_sql = find_tool(tools, "execute_polars_sql")
    results = []
    for metric in metrics:
        try:
            rows = parse_rows(
                await execute_sql.ainvoke(
                    {"file_locations": [file_path], "query": metric["sql"], "file_type": "csv"}
                )
            )
        except Exception:
            logger.exception("Skipping metric %r: its SQL failed", metric.get("metric"))
            continue
        results.append(
            {
                "metric": metric["metric"],
                "description": metric["description"],
                "visualization_type": metric["visualization_type"],
                "data": rows,
            }
        )
    if not results:
        raise RuntimeError("None of the generated SQL queries could be executed")
    return results


async def render_dashboard(llm: BaseChatModel, metrics_data: list[dict]) -> str:
    response = await llm.ainvoke(
        [
            SystemMessage(content=RENDER_DASHBOARD_PROMPT),
            HumanMessage(content=json.dumps({"metrics": metrics_data})),
        ]
    )
    return strip_code_fence(response.content)


async def run_dashboard_agent(question: str, connection: McpConnection) -> str:
    """Return a self-contained HTML dashboard for the CSV the MCP server exposes."""
    async with open_mcp_tools(connection) as tools:
        data = await load_data_context(tools)
        if not data.schema:
            raise RuntimeError("No file is present, so there is nothing to build a dashboard from")

        metrics = await plan_metrics(create_llm(), data, question)
        results = await run_metric_queries(tools, metrics, data.file_path)
        return await render_dashboard(create_llm(), results)

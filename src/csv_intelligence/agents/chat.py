"""Chat: question -> SQL (LLM call 1) -> run on MCP -> insights (LLM call 2, only when privacy allows).

There is no agent loop: the LLM never calls tools and never sees tool output it was not meant to.
If the SQL fails, one extra call fixes it, given a redacted error message.
"""

import re
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel

from csv_intelligence.agents.audit import LlmAudit
from csv_intelligence.agents.dataset import NO_DATASET_MESSAGE, active_dataset
from csv_intelligence.agents.mcp_client import McpClient, ToolCallError
from csv_intelligence.agents.parsing import message_text, parse_sql_reply
from csv_intelligence.agents.privacy import insight_decision, local_summary, schema_for_llm
from csv_intelligence.agents.prompts import INSIGHTS_PROMPT, WRITE_SQL_PROMPT
from csv_intelligence.sql.guard import parse_select
from csv_intelligence.timing import Timer

ERROR_PREVIEW_CHARS = 300


def redact_error(message: str) -> str:
    """First line of an error, with bracketed value lists removed (Polars can quote data in them)."""
    first_line = message.strip().splitlines()[0] if message.strip() else "unknown error"
    return re.sub(r"\[[^\]]*\]", "[…]", first_line)[:ERROR_PREVIEW_CHARS]


async def write_sql(llm: BaseChatModel, audit: LlmAudit, step: str, payload: dict[str, Any]) -> str:
    reply = await llm.ainvoke(audit.messages(step, WRITE_SQL_PROMPT, payload))
    return parse_sql_reply(message_text(reply.content))


async def run_sql(mcp: McpClient, timer: Timer, dataset: str, sql: str) -> dict[str, Any]:
    """Run SQL on the server; record the round trip and the server's own steps (filter matching, query)."""
    with timer.step("run_sql"):
        result = await mcp.call("run_sql", {"dataset": dataset, "query": sql})
    for step, ms in result.get("timings_ms", {}).items():
        timer.record(f"server_{step}", ms)
    return result


async def query_with_one_fix(
    mcp: McpClient,
    llm: BaseChatModel,
    audit: LlmAudit,
    timer: Timer,
    dataset: str,
    question_payload: dict[str, Any],
) -> dict[str, Any]:
    """Write SQL and run it; if the server rejects it, ask the LLM once to fix it."""
    with timer.step("write_sql"):
        sql = await write_sql(llm, audit, "write_sql", question_payload)
    try:
        return await run_sql(mcp, timer, dataset, sql)
    except ToolCallError as error:
        retry_payload = {**question_payload, "previous_sql": sql, "error": redact_error(str(error))}
        with timer.step("fix_sql"):
            sql = await write_sql(llm, audit, "fix_sql", retry_payload)
        return await run_sql(mcp, timer, dataset, sql)


async def stream_insights(
    llm: BaseChatModel, audit: LlmAudit, question: str, result: dict[str, Any]
) -> AsyncIterator[str]:
    payload = {
        "question": question,
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": result["rows"],
    }
    async for chunk in llm.astream(audit.messages("write_insights", INSIGHTS_PROMPT, payload)):
        text = message_text(chunk.content)
        if text:
            yield text


async def answer_question(
    question: str, mcp: McpClient, llm: BaseChatModel, mode: str, insight_max_rows: int
) -> AsyncIterator[dict[str, Any]]:
    """Answer one question as a stream of events, so the UI can show the table before the insights.

    Events, in order: sql, table, privacy, then insight chunks or one summary, then done.
    An error event ends the stream early. done carries the audit ("What the AI saw") and timings_ms:
    load_dataset, write_sql, run_sql (round trip) with server_check_sql, server_match_filters and
    server_query inside it, fix_sql when needed, privacy_check, then insights (LLM) or local_summary,
    and total.
    """
    audit, timer = LlmAudit(), Timer()
    with timer.step("load_dataset"):
        dataset = await active_dataset(mcp)
    if dataset is None:
        yield {"type": "error", "message": NO_DATASET_MESSAGE, "audit": [], "timings_ms": timer.report()}
        return
    name, profile = dataset

    try:
        result = await query_with_one_fix(
            mcp, llm, audit, timer, name, {"question": question, "schema": schema_for_llm(profile)}
        )
    except (ToolCallError, ValueError) as error:
        yield {"type": "error", "message": str(error), "audit": audit.calls, "timings_ms": timer.report()}
        return

    yield {"type": "sql", "sql": result["sql"], "filter_matches": result["filter_matches"]}
    yield {"type": "table", **{key: result[key] for key in ("columns", "rows", "row_count", "truncated")}}

    with timer.step("privacy_check"):
        decision = insight_decision(mode, parse_select(result["sql"]), result, profile, insight_max_rows)
    yield {"type": "privacy", "results_sent": decision.allowed, "reason": decision.reason}
    if decision.allowed:
        with timer.step("insights"):
            async for text in stream_insights(llm, audit, question, result):
                yield {"type": "insight", "text": text}
    else:
        with timer.step("local_summary"):
            summary = local_summary(result)
        yield {"type": "summary", "text": summary}

    yield {"type": "done", "audit": audit.calls, "timings_ms": timer.report()}


async def collect_answer(events: AsyncIterator[dict[str, Any]]) -> dict[str, Any]:
    """Gather a full answer from the event stream (for non-streaming callers such as scripts)."""
    answer: dict[str, Any] = {"insight": ""}
    async for event in events:
        if event["type"] == "insight":
            answer["insight"] += event["text"]
        else:
            answer[event["type"]] = event
    return answer

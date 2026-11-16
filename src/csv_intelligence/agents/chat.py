"""Chat: question -> SQL (LLM call 1) -> run on MCP -> insights (LLM call 2, only when privacy allows).

There is no agent loop: the LLM never calls tools and never sees tool output it was not meant to.
If the SQL fails, one extra call fixes it, given a redacted error message.
"""

import re
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.language_models import BaseChatModel

from csv_intelligence.agents.audit import LlmAudit
from csv_intelligence.agents.dataset import NO_DATASET_MESSAGE, active_dataset
from csv_intelligence.agents.mcp_client import McpClient, ToolCallError
from csv_intelligence.agents.parsing import message_text, parse_sql_reply
from csv_intelligence.agents.privacy import insight_decision, local_summary, schema_for_llm
from csv_intelligence.agents.prompts import INSIGHTS_PROMPT, WRITE_SQL_PROMPT
from csv_intelligence.sql.guard import parse_select

ERROR_PREVIEW_CHARS = 300


class StepTimer:
    """Milliseconds per pipeline step, reported with every answer."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = round((time.perf_counter() - start) * 1000)


def redact_error(message: str) -> str:
    """First line of an error, with bracketed value lists removed (Polars can quote data in them)."""
    first_line = message.strip().splitlines()[0] if message.strip() else "unknown error"
    return re.sub(r"\[[^\]]*\]", "[…]", first_line)[:ERROR_PREVIEW_CHARS]


async def write_sql(llm: BaseChatModel, audit: LlmAudit, step: str, payload: dict[str, Any]) -> str:
    reply = await llm.ainvoke(audit.messages(step, WRITE_SQL_PROMPT, payload))
    return parse_sql_reply(message_text(reply.content))


async def query_with_one_fix(
    mcp: McpClient, llm: BaseChatModel, audit: LlmAudit, dataset: str, question_payload: dict[str, Any]
) -> dict[str, Any]:
    """Write SQL and run it; if the server rejects it, ask the LLM once to fix it."""
    sql = await write_sql(llm, audit, "write_sql", question_payload)
    try:
        return await mcp.call("run_sql", {"dataset": dataset, "query": sql})
    except ToolCallError as error:
        retry_payload = {**question_payload, "previous_sql": sql, "error": redact_error(str(error))}
        sql = await write_sql(llm, audit, "fix_sql", retry_payload)
        return await mcp.call("run_sql", {"dataset": dataset, "query": sql})


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
    An error event ends the stream early. done carries the audit ("What the AI saw") and timings.
    """
    audit, timer = LlmAudit(), StepTimer()
    dataset = await active_dataset(mcp)
    if dataset is None:
        yield {"type": "error", "message": NO_DATASET_MESSAGE, "audit": [], "timings_ms": {}}
        return
    name, profile = dataset

    try:
        with timer.step("sql"):
            result = await query_with_one_fix(
                mcp, llm, audit, name, {"question": question, "schema": schema_for_llm(profile)}
            )
    except (ToolCallError, ValueError) as error:
        yield {"type": "error", "message": str(error), "audit": audit.calls, "timings_ms": timer.ms}
        return

    yield {"type": "sql", "sql": result["sql"], "filter_matches": result["filter_matches"]}
    yield {"type": "table", **{key: result[key] for key in ("columns", "rows", "row_count", "truncated")}}

    decision = insight_decision(mode, parse_select(result["sql"]), result, profile, insight_max_rows)
    yield {"type": "privacy", "results_sent": decision.allowed, "reason": decision.reason}
    with timer.step("insights"):
        if decision.allowed:
            async for text in stream_insights(llm, audit, question, result):
                yield {"type": "insight", "text": text}
        else:
            yield {"type": "summary", "text": local_summary(result)}

    yield {"type": "done", "audit": audit.calls, "timings_ms": timer.ms}


async def collect_answer(events: AsyncIterator[dict[str, Any]]) -> dict[str, Any]:
    """Gather a full answer from the event stream (for non-streaming callers such as scripts)."""
    answer: dict[str, Any] = {"insight": ""}
    async for event in events:
        if event["type"] == "insight":
            answer["insight"] += event["text"]
        else:
            answer[event["type"]] = event
    return answer

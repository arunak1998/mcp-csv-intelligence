"""Pure helpers that read LLM output."""

import json
import re
from typing import Any

CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", re.DOTALL)
SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def strip_code_fence(text: str) -> str:
    """Remove a surrounding ```lang ... ``` fence that models add despite instructions."""
    match = CODE_FENCE.match(text.strip())
    return match.group(1) if match else text.strip()


def parse_json_object(text: str) -> dict:
    return json.loads(strip_code_fence(text))


def message_text(content: Any) -> str:
    """Text of a LangChain message's content, which is a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") if isinstance(block, dict) else str(block) for block in content or []
    )


def parse_sql_reply(text: str) -> str:
    """The SQL in the model's reply: {"sql": "..."} as asked, or a bare SELECT/WITH as a fallback."""
    try:
        reply = parse_json_object(text)
    except json.JSONDecodeError:
        reply = None
    if isinstance(reply, dict) and isinstance(reply.get("sql"), str) and reply["sql"].strip():
        return reply["sql"].strip()
    bare = strip_code_fence(text)
    if SQL_START.match(bare):
        return bare
    raise ValueError("The model did not return a SQL query")

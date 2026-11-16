"""Pure helpers that normalise MCP tool results and LLM output."""

import json
import re
from dataclasses import dataclass
from typing import Any

CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", re.DOTALL)
SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DataContext:
    """The file the agents work on and its column names/types."""

    file_path: str
    schema: dict[str, str]

    def schema_as_list(self) -> list[dict[str, str]]:
        return [{"name": name, "dtype": dtype} for name, dtype in self.schema.items()]


def _decode(value: Any) -> Any:
    """Decode JSON strings; leave anything else (including plain paths) untouched."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _unwrap_text_blocks(items: list) -> list:
    """Newer langchain-mcp-adapters return [{"type": "text", "text": ...}] blocks instead of strings."""
    return [item["text"] if isinstance(item, dict) and item.get("type") == "text" else item for item in items]


def _as_list(value: Any) -> list:
    decoded = _decode(value)
    return _unwrap_text_blocks(decoded) if isinstance(decoded, list) else [decoded]


def parse_file_list(raw: Any) -> list[str]:
    """Normalise a tool's list-of-paths result, whichever shape the MCP adapter produced."""
    return [str(item) for item in _as_list(raw) if item]


def parse_schema(raw: Any) -> dict[str, str]:
    columns = [_decode(item) for item in _as_list(raw)]
    return {column["name"]: column["dtype"] for column in columns}


def parse_rows(raw: Any) -> list[dict]:
    """Normalise a SQL tool result into row dicts.

    The server reports SQL errors as plain text instead of raising, so a non-row means failure.
    """
    rows = [_decode(item) for item in _as_list(raw)]
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"SQL tool did not return rows: {str(row)[:200]}")
    return rows


def strip_code_fence(text: str) -> str:
    """Remove a surrounding ```lang ... ``` fence that models add despite instructions."""
    match = CODE_FENCE.match(text.strip())
    return match.group(1) if match else text.strip()


def parse_json_object(text: str) -> dict:
    return json.loads(strip_code_fence(text))


def strip_end_marker(answer: str) -> str:
    """The CSV prompt asks the model to finish with a bare END line; hide it from users."""
    answer = answer.rstrip()
    return answer.removesuffix("END").rstrip()


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

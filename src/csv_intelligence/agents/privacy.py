"""What may be sent to the LLM, and the local fallback when the answer must stay on this machine.

Rules:
1. Prompts carry the schema and summary statistics only, never rows (schema_for_llm).
2. After a query runs, its result may be sent for insights only if it is a small aggregate
   that does not touch unmasked personal data (insight_decision).
3. In strict mode no result is ever sent; the summary is written locally (local_summary).
"""

from dataclasses import dataclass
from typing import Any

from sqlglot import exp

from csv_intelligence.formatting import format_value, is_number
from csv_intelligence.sql.analysis import group_by_columns, referenced_columns, returns_only_aggregates

SCHEMA_KEYS = ("name", "dtype", "nulls", "distinct", "min", "max", "mean", "masked")


def schema_for_llm(profile: dict[str, Any]) -> dict[str, Any]:
    """Row count plus per-column name, type and stats. No values, file name or PII kind are included."""
    return {
        "row_count": profile["row_count"],
        "columns": [
            {key: column[key] for key in SCHEMA_KEYS if key in column} for column in profile["columns"]
        ],
    }


@dataclass(frozen=True)
class InsightDecision:
    allowed: bool
    reason: str


def _unmasked_personal_columns(profile: dict[str, Any]) -> set[str]:
    return {column["name"] for column in profile["columns"] if column.get("pii") and not column.get("masked")}


def _unique_columns(profile: dict[str, Any]) -> set[str]:
    """Columns where every row has its own value (IDs): grouping by them returns row-level data."""
    return {column["name"] for column in profile["columns"] if column["distinct"] >= profile["row_count"] > 1}


def insight_decision(
    mode: str, tree: exp.Expression, result: dict[str, Any], profile: dict[str, Any], max_rows: int
) -> InsightDecision:
    """May this query result be sent to the LLM to write insights?"""
    if mode == "strict":
        return InsightDecision(False, "Strict mode: query results are never sent to the AI.")
    if not returns_only_aggregates(tree):
        return InsightDecision(False, "The result has row-level values, so it stayed on this machine.")
    if unique := sorted(group_by_columns(tree) & _unique_columns(profile)):
        return InsightDecision(
            False, f"The result is grouped by a unique column ({', '.join(unique)}), so it stayed here."
        )
    if personal := sorted(referenced_columns(tree) & _unmasked_personal_columns(profile)):
        return InsightDecision(
            False, f"The query uses personal-data columns ({', '.join(personal)}), so it stayed here."
        )
    if result["row_count"] > max_rows:
        return InsightDecision(
            False, f"The result has more than {max_rows} rows, so it stayed on this machine."
        )
    return InsightDecision(True, f"Only this {result['row_count']}-row aggregate result was sent to the AI.")


def _first_numeric_column(rows: list[list[Any]], start: int) -> int | None:
    for index in range(start, len(rows[0])):
        if all(is_number(row[index]) for row in rows):
            return index
    return None


def local_summary(result: dict[str, Any]) -> str:
    """A one-paragraph answer written on this machine from the result table (no LLM involved)."""
    columns, rows = result["columns"], result["rows"]
    if not rows:
        return "The query returned no rows."
    if len(rows) == 1:
        return ", ".join(
            f"**{column}**: {format_value(value)}" for column, value in zip(columns, rows[0], strict=True)
        )

    summary = (
        f"{result['row_count']:,} rows" + (" (showing the first ones)" if result["truncated"] else "") + "."
    )
    measure = _first_numeric_column(rows, start=1)
    if measure is None:
        return summary
    top = max(rows, key=lambda row: row[measure])
    bottom = min(rows, key=lambda row: row[measure])
    name = columns[measure]
    return (
        f"{summary} Highest {name}: **{format_value(top[0])}** ({format_value(top[measure])}). "
        f"Lowest: **{format_value(bottom[0])}** ({format_value(bottom[measure])})."
    )

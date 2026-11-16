"""Turn metric results into a chart spec: plain JSON the template renders. No LLM is involved here."""

from typing import Any

from csv_intelligence.formatting import format_value, is_number, label_text

CHART_TYPES = ("kpi", "bar", "line", "share", "table")
MAX_POINTS = 50  # bars or line points per chart
MAX_SERIES = 3  # the palette's first three colours stay distinct for every kind of colour vision
MAX_SHARE_PARTS = 8  # beyond this the rest is folded into "Other"
MAX_TABLE_ROWS = 15


def _numeric_columns(rows: list[list[Any]], start: int = 1) -> list[int]:
    return [index for index in range(start, len(rows[0])) if all(is_number(row[index]) for row in rows)]


def _kpi(rows: list[list[Any]]) -> dict[str, Any]:
    numbers = [value for value in rows[0] if is_number(value)]
    return {"chart": "kpi", "value": format_value(numbers[0] if numbers else rows[0][0])}


def _series_chart(
    chart: str, columns: list[str], rows: list[list[Any]], numeric: list[int]
) -> dict[str, Any]:
    rows = rows[:MAX_POINTS]
    return {
        "chart": chart,
        "labels": [label_text(row[0]) for row in rows],
        "datasets": [
            {"label": columns[index], "data": [row[index] for row in rows]} for index in numeric[:MAX_SERIES]
        ],
    }


def _share(columns: list[str], rows: list[list[Any]], value_index: int) -> dict[str, Any]:
    """Part of a whole as ranked bars of percentage share, folding the tail into 'Other'."""
    ranked = sorted(rows, key=lambda row: row[value_index], reverse=True)
    parts = [(label_text(row[0]), row[value_index]) for row in ranked]
    if len(parts) > MAX_SHARE_PARTS:
        kept = parts[: MAX_SHARE_PARTS - 1]
        parts = [*kept, ("Other", sum(value for _, value in parts[MAX_SHARE_PARTS - 1 :]))]
    total = sum(value for _, value in parts) or 1
    return {
        "chart": "share",
        "labels": [label for label, _ in parts],
        "datasets": [
            {
                "label": f"Share of {columns[value_index]} (%)",
                "data": [round(100 * value / total, 1) for _, value in parts],
            }
        ],
    }


def _table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    shown = rows[:MAX_TABLE_ROWS]
    return {
        "chart": "table",
        "columns": columns,
        "numeric": [all(is_number(row[index]) for row in shown) for index in range(len(columns))],
        "rows": [[format_value(value) for value in row] for row in shown],
    }


def build_panel(chart: str, result: dict[str, Any]) -> dict[str, Any]:
    """The panel body for one metric result; falls back to a table when the data doesn't fit the chart."""
    columns, rows = result["columns"], result["rows"]
    if not rows:
        return {"chart": "empty"}
    if chart == "kpi":
        return _kpi(rows)
    numeric = _numeric_columns(rows) if len(columns) > 1 else []
    if chart in ("bar", "line") and numeric:
        return _series_chart(chart, columns, rows, numeric)
    if chart == "share" and numeric:
        return _share(columns, rows, numeric[0])
    return _table(columns, rows)


def build_spec(title: str, question: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """metrics: the plan's entries, each with either a "result" from run_sql or an "error"."""
    panels, skipped = [], []
    for metric in metrics:
        heading = {"title": metric.get("title") or "Metric", "description": metric.get("description") or ""}
        if "error" in metric:
            skipped.append({**heading, "reason": metric["error"]})
            continue
        panels.append({"id": len(panels), **heading, **build_panel(metric["chart"], metric["result"])})
    return {"title": title, "question": question, "panels": panels, "skipped": skipped}

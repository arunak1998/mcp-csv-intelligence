"""How numbers are shown to people (summaries, KPI tiles, tables)."""

from typing import Any


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def format_value(value: Any) -> str:
    """1234567 -> '1,234,567'; 1234.5 -> '1,234.50'; anything else as text."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)

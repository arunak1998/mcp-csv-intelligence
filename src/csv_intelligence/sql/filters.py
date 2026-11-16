"""Match filter values the LLM wrote ('south') to the values really stored ('South'), on this machine."""

import difflib

import sqlglot
from sqlglot.tokens import TokenType

from csv_intelligence.sql.guard import DIALECT

# How similar a value must be to count as a typo of a stored value (difflib ratio, 0..1).
FUZZY_CUTOFF = 0.8


def closest_value(requested: str, stored: list[str]) -> str | None:
    """The stored value requested most likely means, or None when nothing is close.

    Tries an exact match, then a case/whitespace-insensitive one, then a close spelling.
    """
    if requested in stored:
        return requested
    by_folded: dict[str, str] = {}
    for value in stored:
        by_folded.setdefault(value.strip().casefold(), value)
    folded = requested.strip().casefold()
    if folded in by_folded:
        return by_folded[folded]
    close = difflib.get_close_matches(folded, list(by_folded), n=1, cutoff=FUZZY_CUTOFF)
    return by_folded[close[0]] if close else None


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def replace_string_literals(sql: str, replacements: dict[str, str]) -> str:
    """Swap string literals in sql by token position, leaving every other character untouched."""
    if not replacements:
        return sql
    tokens = sqlglot.Dialect.get_or_raise(DIALECT).tokenize(sql)
    pieces, cursor = [], 0
    for token in tokens:
        if token.token_type == TokenType.STRING and token.text in replacements:
            pieces.append(sql[cursor : token.start])
            pieces.append(_quote(replacements[token.text]))
            cursor = token.end + 1
    pieces.append(sql[cursor:])
    return "".join(pieces)

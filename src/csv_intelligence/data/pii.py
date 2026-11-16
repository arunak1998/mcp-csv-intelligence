"""Find columns that look like personal data, and mask or rename them before the dataset is saved.

Detection is a heuristic, not a guarantee:
- email / phone: at least half of a sample of text values match the pattern, or the header says so;
- name: the header says so ("name", "customer_name", "First Name", ...). Values alone can't
  tell a person's name from a product name, so values are not used for names.
"""

import re
import secrets
from dataclasses import dataclass
from typing import Any

import polars as pl

SAMPLE_SIZE = 1_000
MATCH_SHARE = 0.5

EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
PHONE = re.compile(r"^\+?[\d\s().-]{7,20}$")
PHONE_DIGITS = (7, 15)

EMAIL_HEADERS = {"email", "emailaddress", "mail"}
PHONE_HEADERS = {
    "phone",
    "phonenumber",
    "mobile",
    "mobilenumber",
    "cell",
    "telephone",
    "tel",
    "contactnumber",
}
NAME_HEADERS = {"name", "fullname", "firstname", "lastname", "surname", "middlename", "givenname"}
PERSON_PREFIXES = {
    "customer",
    "contact",
    "employee",
    "patient",
    "person",
    "user",
    "client",
    "owner",
    "member",
}


@dataclass(frozen=True)
class PiiFinding:
    column: str
    kind: str  # "email" | "phone" | "name"
    reason: str


def _normalise_header(column: str) -> str:
    return re.sub(r"[^a-z0-9]", "", column.lower())


def _header_kind(column: str) -> str | None:
    header = _normalise_header(column)
    if header in EMAIL_HEADERS:
        return "email"
    if header in PHONE_HEADERS:
        return "phone"
    if header in NAME_HEADERS or any(header == f"{prefix}name" for prefix in PERSON_PREFIXES):
        return "name"
    return None


def _looks_like_phone(value: str) -> bool:
    digits = sum(character.isdigit() for character in value)
    return bool(PHONE.match(value)) and PHONE_DIGITS[0] <= digits <= PHONE_DIGITS[1]


def _value_kind(series: pl.Series) -> tuple[str, float] | None:
    """The kind most sampled text values match, with the share that matched."""
    if series.dtype != pl.String:
        return None
    sample = series.drop_nulls().head(SAMPLE_SIZE).str.strip_chars().to_list()
    if not sample:
        return None
    for kind, test in (("email", EMAIL.match), ("phone", _looks_like_phone)):
        share = sum(bool(test(value)) for value in sample) / len(sample)
        if share >= MATCH_SHARE:
            return kind, share
    return None


def scan_pii(df: pl.DataFrame) -> list[PiiFinding]:
    findings = []
    for column in df.columns:
        by_values = _value_kind(df[column])
        if by_values:
            kind, share = by_values
            findings.append(PiiFinding(column, kind, f"{share:.0%} of sampled values look like {kind}s"))
        elif kind := _header_kind(column):
            findings.append(PiiFinding(column, kind, f"the column name suggests a {kind}"))
    return findings


def mask_expression(column: str, prefix: str, seed: int) -> pl.Expr:
    """Replace each value with a stable token like 'email_4821…'.

    Equal values get equal tokens, so COUNT(DISTINCT ...) and GROUP BY still work.
    The seed is random per upload and never stored, so tokens can't be reversed by
    hashing guessed values.
    """
    token = pl.lit(f"{prefix}_") + pl.col(column).cast(pl.String).hash(seed).cast(pl.String).str.slice(0, 12)
    return pl.when(pl.col(column).is_null()).then(None).otherwise(token).alias(column)


def _validated_renames(df: pl.DataFrame, choices: dict[str, dict[str, Any]]) -> dict[str, str]:
    renames = {
        column: choice["rename"].strip()
        for column, choice in choices.items()
        if (choice.get("rename") or "").strip() and choice["rename"].strip() != column
    }
    final = [renames.get(column, column) for column in df.columns]
    if len(set(final)) != len(final):
        raise ValueError("Renaming would create two columns with the same name")
    return renames


def apply_privacy_choices(
    df: pl.DataFrame, findings: list[PiiFinding], choices: dict[str, dict[str, Any]]
) -> tuple[pl.DataFrame, dict[str, dict[str, Any]]]:
    """Mask and rename columns as chosen; return the new frame and per-column privacy flags.

    choices: {column: {"mask": bool, "rename": "new name" | None}}. Any column may be masked or
    renamed, not only detected ones. Flags are keyed by the final column name.
    """
    unknown = set(choices) - set(df.columns)
    if unknown:
        raise ValueError(f"Unknown columns: {sorted(unknown)}")
    kinds = {finding.column: finding.kind for finding in findings}
    seed = secrets.randbits(63)
    masked = [column for column, choice in choices.items() if choice.get("mask")]
    df = df.with_columns(mask_expression(column, kinds.get(column, "masked"), seed) for column in masked)

    renames = _validated_renames(df, choices)
    flags = {
        renames.get(column, column): {"pii": kinds.get(column), "masked": column in masked}
        for column in set(kinds) | set(masked)
    }
    return df.rename(renames), flags

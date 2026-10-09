"""Polars SQL functions the `execute_polars_sql` tool advertises to the LLM."""

_AGGREGATE = [
    "avg",
    "count",
    "first",
    "last",
    "max",
    "median",
    "min",
    "quantile_count",
    "quantile_disc",
    "stddev",
    "sum",
    "variance",
]

_ARRAY = [
    "array_agg",
    "array_contains",
    "array_get",
    "array_length",
    "array_lower",
    "array_mean",
    "array_reverse",
    "array_sum",
    "array_to_string",
    "array_unique",
    "array_upper",
    "unnest",
]

_BITWISE = [
    "bit_and",
    "bit_count",
    "bit_or",
    "bit_xor",
]

_CONDITIONAL = [
    "coalesce",
    "greatest",
    "if",
    "ifnull",
    "least",
    "nullif",
]

_MATHEMATICAL = [
    "abs",
    "cbrt",
    "ceil",
    "div",
    "exp",
    "floor",
    "ln",
    "log2",
    "log10",
    "mod",
    "pi",
    "pow",
    "round",
    "sign",
    "sqrt",
]

_STRING = [
    "bit_length",
    "concat",
    "concat_ws",
    "date",
    "ends_with",
    "initcap",
    "left",
    "length",
    "lower",
    "ltrim",
    "normalize",
    "octet_length",
    "regexp_like",
    "replace",
    "reverse",
    "right",
    "rtrim",
    "starts_with",
    "strpos",
    "strptime",
    "substr",
    "timestamp",
    "upper",
]

_TEMPORAL = [
    "date_part",
    "extract",
    "strftime",
]

_TYPE = [
    "cast",
    "try_cast",
]

_TRIGONOMETRIC = [
    "acos",
    "acosd",
    "asin",
    "asind",
    "atan",
    "atand",
    "atan2",
    "atan2d",
    "cot",
    "cotd",
    "cos",
    "cosd",
    "degrees",
    "radians",
    "sin",
    "sind",
    "tan",
    "tand",
]

SQL_FUNCTIONS = {
    "aggregate": _AGGREGATE,
    "array": _ARRAY,
    "bitwise": _BITWISE,
    "conditional": _CONDITIONAL,
    "mathematical": _MATHEMATICAL,
    "string": _STRING,
    "temporal": _TEMPORAL,
    "type": _TYPE,
    "trigonometric": _TRIGONOMETRIC,
}


def describe_sql_functions() -> str:
    """Render the function catalogue as a categorised bullet list for the tool description."""
    sections = []
    for category, functions in SQL_FUNCTIONS.items():
        bullets = "\n".join(f"- {fn.capitalize()}" for fn in functions)
        sections.append(f"{category.capitalize()}:\n{bullets}\n")
    return "\n".join(sections)

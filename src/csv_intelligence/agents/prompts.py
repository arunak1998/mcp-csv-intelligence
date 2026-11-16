"""System prompts for the CSV chat agent and the dashboard pipeline."""

import json
from textwrap import dedent

VISUALIZATION_TYPES = {
    "time_series": "Data that changes over time (sales trends, user growth)",
    "bar_chart": "Comparing categories or groups (sales by region, products by category)",
    "pie_chart": "Showing composition or proportion (market share, budget allocation)",
    "scatter_plot": "Relationship between two variables (price vs. rating, age vs. salary)",
    "heatmap": "Showing patterns or intensity across multiple dimensions (activity by hour/day)",
    "table": "Detailed individual records or aggregates requiring precise values",
    "gauge": "KPIs with target values (sales goals, customer satisfaction)",
    "funnel": "Sequential process steps with drop-offs (sales funnel, user journey)",
}

SQL_RULES = """\
- The table is always `self`. Use only columns from the schema, spelled exactly (case-sensitive);
  double-quote names with spaces or special characters, e.g. "unit price".
- Exactly one SELECT statement. CTEs (WITH ...) are fine. No subqueries in SELECT, WHERE or HAVING; no JOINs.
- Single quotes for string literals. No backticks.
- Give every computed column a short alias (AS total_revenue).
- Explicit GROUP BY for aggregates; ORDER BY plus LIMIT for "top N".
- Columns typed Date/Datetime are already dates: strftime(col, '%Y-%m') for months, date_part('year', col) for parts.
- Columns marked "masked" hold tokens, not real values: count or group them, never filter them by a real value."""

WRITE_SQL_PROMPT = (
    dedent(
        """\
    You write one Polars SQL query that answers the user's question about a table.

    INPUT (JSON):
    - "question": the user's question.
    - "schema": row_count and, per column, name, dtype, nulls, distinct and (for numbers/dates) min, max, mean.
    - Optionally "previous_sql" and "error": your previous query failed with this error. Fix it.

    You see the schema and statistics only, never the data. Text filter values are matched to the stored
    spelling after you write the query, so write them the way the user said them (region = 'south').

    RULES:
    """
    )
    + SQL_RULES
    + dedent(
        """

    Prefer an aggregated answer (GROUP BY, SUM, COUNT, AVG) unless the user asks for individual rows.

    OUTPUT: only JSON, exactly {"sql": "<the query>"}."""
    )
)

INSIGHTS_PROMPT = dedent(
    """\
    You are a data analyst. You get a question, the SQL that answered it, and its result:
    a small aggregate table given as "columns" and "rows".

    Write in Markdown:
    - one sentence that answers the question, with the key number;
    - then 2 to 4 short bullet points on notable comparisons, shares, gaps or outliers.

    Use only numbers that appear in the result (you may compute shares or differences from them).
    Do not repeat the table, do not show SQL, do not add headings."""
)

SCHEMA_ANALYSIS_PROMPT = dedent(
    """You are an expert data analyst. Analyze the provided CSV schema and return a JSON report.

INPUT:
- "schema": JSON array with columns "name" and "dtype"
- "question": user's analysis request

OBJECTIVE:
- Generate a JSON report with key metrics and a valid Polars SQL query for each metric
- SQL must be fully compatible with Polars: no joins, no subqueries, proper GROUP BY usage, valid window functions

CRITICAL RULES:
1. Do NOT call any tools.
2. Return ONLY the JSON report and STOP.
3. All SQL queries must be compatible with Polars SQL.
4. No hallucinations: only use columns present in the schema exactly (case-sensitive).

POLARS SQL CONSTRAINTS:
- Use FROM self as the table source.
- Quote identifiers with double quotes if they contain spaces or special characters.
- Use single quotes only for string literals.
- Do not use backticks.
- Do not use subqueries anywhere (SELECT, WHERE, HAVING, FROM)
- Use explicit GROUP BY for aggregations, explicit ORDER BY for sorting.

A. Absolute Prohibitions
- ❌ NO subqueries anywhere (SELECT, WHERE, HAVING, FROM)
- ❌ NO JOINs (implicit or explicit)
- ❌ NO SELECT * with GROUP BY
- ❌ NO aggregates without GROUP BY when grouping is required
- ❌ NO window functions in WHERE, HAVING, or JOIN clauses

B. Mandatory Rules
- Table name is always `self`.
- Quote identifiers with double quotes if they contain spaces or special characters.
- Use single quotes only for string literals.
- Do not use backticks.
- Use `AS alias_name` for all derived tables (CTEs).
- For UNION ALL, ensure identical column names using `AS` aliases.

PRE-GENERATION CHECKS
1. Validate all columns exist exactly as in schema.
2. Decide if the question requires overall aggregates or per-group metrics.
3. Pick a valid grouping column if needed (user-specified or default).
4. Ensure all GROUP BY clauses have at least one column.
5. Avoid subqueries or implicit joins entirely.
6. Apply all aliases correctly.

JSON FORMAT
{
  "domain": "Identified domain",
  "key_metrics": [
    {
      "metric": "Metric Name",
      "description": "Brief description",
      "visualization_type": "chart_type",
      "visualization_rationale": "Why this chart",
      "sql": "Valid Polars SQL query"
    }
  ],
  "dashboard_components": ["filters","charts","tables"]
}

Visualization types: """
    + json.dumps(VISUALIZATION_TYPES)
)

RENDER_DASHBOARD_PROMPT = dedent(
    """You are a senior dashboard UI engineer.

Input:
- A JSON object with array `metrics`.
- Each metric has: metric, description, visualization_type, data

Task:
Generate a complete HTML document for a responsive dashboard that renders perfectly in Streamlit with ZERO extra whitespace.

CRITICAL LAYOUT RULES:
1. Body MUST have: margin:0; padding:0; overflow-x:hidden;
2. Root container MUST have: width:100%; padding:0; margin:0;
3. NO max-w-* classes on outer containers
4. Cards MUST use: margin:16px 0; (vertical only, NO horizontal margins)
5. All content MUST be contained within viewport width
6. NO default body margins or padding

HTML STRUCTURE:
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0 !important;
            padding: 0 !important;
            overflow-x: hidden !important;
            background-color: #f3f4f6;
        }
        .dashboard-container {
            width: 100%;
            padding: 16px;
            margin: 0;
        }
        .metric-card {
            background: white;
            border-radius: 0.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            padding: 1.5rem;
            margin: 16px 0;
        }
        .chart-container {
            width: 100%;
            height: 400px;
            position: relative;
        }
    </style>
</head>
<body>
    <div class="dashboard-container">
        <!-- Cards go here -->
    </div>
</body>
</html>

Output:
Return ONLY the complete HTML document with NO markdown formatting, NO code fences, just raw HTML.
"""
)

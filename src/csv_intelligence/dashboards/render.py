"""Render a chart spec to one self-contained HTML page (Chart.js is inlined; no CDN, no network)."""

from functools import cache
from importlib.resources import files
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape


@cache
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("csv_intelligence.dashboards", "templates"),
        autoescape=select_autoescape(["html"]),
    )


@cache
def _chart_js() -> str:
    return (files("csv_intelligence.dashboards") / "static" / "chart.umd.min.js").read_text(encoding="utf-8")


def render_dashboard(spec: dict[str, Any]) -> str:
    return _environment().get_template("dashboard.html").render(spec=spec, chart_js=_chart_js())

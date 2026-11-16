from csv_intelligence.dashboards.render import render_dashboard
from csv_intelligence.dashboards.spec import build_panel, build_spec


def result(columns, rows):
    return {"columns": columns, "rows": rows}


def test_kpi_shows_the_first_number_formatted():
    assert build_panel("kpi", result(["total"], [[1234567]])) == {"chart": "kpi", "value": "1,234,567"}


def test_bar_uses_first_column_as_labels_and_caps_series_at_three():
    panel = build_panel(
        "bar", result(["region", "a", "b", "c", "d"], [["North", 1, 2, 3, 4], ["South", 5, 6, 7, 8]])
    )
    assert panel["labels"] == ["North", "South"]
    assert [dataset["label"] for dataset in panel["datasets"]] == ["a", "b", "c"]


def test_share_ranks_parts_as_percentages_and_folds_the_tail():
    rows = [[f"p{i}", 10] for i in range(9)] + [["big", 10]]
    panel = build_panel("share", result(["part", "value"], rows))
    assert len(panel["labels"]) == 8 and panel["labels"][-1] == "Other"
    assert panel["datasets"][0]["data"][-1] == 30.0
    assert round(sum(panel["datasets"][0]["data"])) == 100


def test_charts_without_numbers_fall_back_to_a_table():
    panel = build_panel("bar", result(["region"], [["North"], ["South"]]))
    assert panel["chart"] == "table" and panel["rows"] == [["North"], ["South"]]


def test_table_formats_values_and_marks_numeric_columns():
    panel = build_panel("table", result(["name", "n"], [["A", 1000], ["B", 2.5]]))
    assert panel["rows"] == [["A", "1,000"], ["B", "2.50"]]
    assert panel["numeric"] == [False, True]


def test_empty_result():
    assert build_panel("bar", result(["a", "b"], [])) == {"chart": "empty"}


def test_spec_keeps_failures_separate():
    spec = build_spec(
        "T",
        "q",
        [
            {"title": "ok", "chart": "kpi", "result": result(["n"], [[3]])},
            {"title": "bad", "chart": "bar", "error": "unable to find column"},
        ],
    )
    assert [panel["title"] for panel in spec["panels"]] == ["ok"]
    assert spec["skipped"] == [{"title": "bad", "description": "", "reason": "unable to find column"}]


def test_rendered_page_is_self_contained_and_escapes_text():
    spec = build_spec(
        "<b>Sales</b>",
        "q",
        [
            {"title": "By region", "chart": "bar", "result": result(["r", "n"], [["</script><x>", 1]])},
            {"title": "Total", "chart": "kpi", "result": result(["n"], [[7]])},
        ],
    )
    html = render_dashboard(spec)

    assert "&lt;b&gt;Sales&lt;/b&gt;" in html
    assert "</script><x>" not in html  # labels are escaped in the table and inside the JSON
    assert "https://" not in html.split("<script>", 1)[0]  # no external stylesheet or script
    assert "cdn." not in html
    assert "Chart.js" in html  # inlined library
    assert 'data-panel="0"' in html

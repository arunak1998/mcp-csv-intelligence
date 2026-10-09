import json

import pytest

from csv_intelligence.agents.parsing import (
    DataContext,
    parse_file_list,
    parse_json_object,
    parse_rows,
    parse_schema,
    strip_code_fence,
    strip_end_marker,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("data/a.csv", ["data/a.csv"]),
        (["data/a.csv", "data/b.csv"], ["data/a.csv", "data/b.csv"]),
        ('["data/a.csv", "data/b.csv"]', ["data/a.csv", "data/b.csv"]),
        ("[]", []),
        ("", []),
        ([{"type": "text", "text": "data/a.csv", "id": "lc_1"}], ["data/a.csv"]),
    ],
)
def test_parse_file_list(raw, expected):
    assert parse_file_list(raw) == expected


def test_parse_schema_from_list_of_json_strings():
    raw = [json.dumps({"name": "a", "dtype": "Int64"}), json.dumps({"name": "b", "dtype": "String"})]
    assert parse_schema(raw) == {"a": "Int64", "b": "String"}


def test_parse_schema_from_adapter_text_blocks():
    raw = [
        {"type": "text", "text": '{\n  "name": "a",\n  "dtype": "Int64"\n}', "id": "lc_1"},
        {"type": "text", "text": '{\n  "name": "b",\n  "dtype": "String"\n}', "id": "lc_2"},
    ]
    assert parse_schema(raw) == {"a": "Int64", "b": "String"}


def test_parse_rows_from_adapter_text_blocks():
    raw = [{"type": "text", "text": '{"region": "East", "total": 5}', "id": "lc_1"}]
    assert parse_rows(raw) == [{"region": "East", "total": 5}]


def test_parse_rows_rejects_tool_error_text():
    raw = [{"type": "text", "text": 'Error executing tool execute_polars_sql: unable to find column "nope"'}]
    with pytest.raises(ValueError, match="did not return rows"):
        parse_rows(raw)


def test_parse_rows_of_empty_result_is_empty():
    assert parse_rows([]) == []


def test_parse_schema_from_single_json_object_string():
    assert parse_schema('{"name": "a", "dtype": "Int64"}') == {"a": "Int64"}


def test_parse_schema_from_json_array_string():
    assert parse_schema('[{"name": "a", "dtype": "Int64"}]') == {"a": "Int64"}


def test_data_context_schema_as_list():
    context = DataContext(file_path="x.csv", schema={"a": "Int64"})
    assert context.schema_as_list() == [{"name": "a", "dtype": "Int64"}]


def test_strip_code_fence():
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence("```html\n<p>hi</p>\n```") == "<p>hi</p>"
    assert strip_code_fence("  <p>plain</p>  ") == "<p>plain</p>"


def test_parse_json_object_accepts_fenced_json():
    assert parse_json_object('```json\n{"key_metrics": []}\n```') == {"key_metrics": []}


def test_strip_end_marker():
    assert strip_end_marker("Answer\nEND") == "Answer"
    assert strip_end_marker("Answer\nEND\n") == "Answer"
    assert strip_end_marker("Answer") == "Answer"

import pytest

from csv_intelligence.agents.parsing import (
    message_text,
    parse_json_object,
    parse_sql_reply,
    strip_code_fence,
)


def test_strip_code_fence():
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence("```html\n<p>hi</p>\n```") == "<p>hi</p>"
    assert strip_code_fence("  <p>plain</p>  ") == "<p>plain</p>"


def test_parse_json_object_accepts_fenced_json():
    assert parse_json_object('```json\n{"key_metrics": []}\n```') == {"key_metrics": []}


@pytest.mark.parametrize(
    "reply, sql",
    [
        ('{"sql": "SELECT 1 AS x"}', "SELECT 1 AS x"),
        ('```json\n{"sql": "SELECT 1 AS x"}\n```', "SELECT 1 AS x"),
        (
            "```sql\nWITH t AS (SELECT 1 AS x) SELECT * FROM t\n```",
            "WITH t AS (SELECT 1 AS x) SELECT * FROM t",
        ),
        ("select 1", "select 1"),
    ],
)
def test_parse_sql_reply(reply, sql):
    assert parse_sql_reply(reply) == sql


@pytest.mark.parametrize("reply", ['{"answer": 42}', "Sorry, no.", '{"sql": ""}'])
def test_parse_sql_reply_rejects_replies_without_sql(reply):
    with pytest.raises(ValueError, match="did not return a SQL query"):
        parse_sql_reply(reply)


def test_message_text_joins_content_blocks():
    assert message_text("plain") == "plain"
    assert message_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "ab"

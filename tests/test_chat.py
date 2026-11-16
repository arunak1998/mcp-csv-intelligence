import json

import pytest

from conftest import InProcessMcp
from csv_intelligence.agents.chat import answer_question, collect_answer, redact_error
from csv_intelligence.agents.dataset import NO_DATASET_MESSAGE

BY_REGION = {"sql": "SELECT region, SUM(revenue) AS total FROM self WHERE region <> 'west' GROUP BY region"}
ROWS = {"sql": "SELECT order_id, revenue FROM self WHERE region = 'south' ORDER BY revenue DESC LIMIT 3"}


async def ask(mcp, llm, question="Revenue by region?", mode="standard"):
    return await collect_answer(answer_question(question, mcp, llm, mode, insight_max_rows=20))


async def test_two_calls_sql_then_insights_from_the_aggregate(mcp, fake_llm):
    llm = fake_llm(json.dumps(BY_REGION), "South leads with 22,728.")

    answer = await ask(mcp, llm)

    assert "region <> 'West'" in answer["sql"]["sql"]  # matched locally
    assert answer["sql"]["filter_matches"] == [{"column": "region", "requested": "west", "matched": "West"}]
    assert answer["table"]["columns"] == ["region", "total"] and answer["table"]["row_count"] == 3
    assert answer["privacy"]["results_sent"] is True
    assert answer["insight"].strip() == "South leads with 22,728."
    assert [call["step"] for call in answer["done"]["audit"]] == ["write_sql", "write_insights"]
    assert set(answer["done"]["timings_ms"]) == {"sql", "insights"}


async def test_the_first_prompt_has_the_schema_but_no_rows_or_values(mcp, fake_llm):
    llm = fake_llm(json.dumps(BY_REGION), "ok")

    answer = await ask(mcp, llm)

    sent = answer["done"]["audit"][0]["user"]
    assert json.loads(sent)["schema"]["row_count"] == 120
    for value in ("North", "South", "Laptop", "sample_sales", "2025-07-22"):
        assert value not in sent
    # the audit holds exactly what the model received
    assert llm.received[0][1].content == sent


async def test_row_level_results_never_reach_the_llm(mcp, fake_llm):
    llm = fake_llm(json.dumps(ROWS))

    answer = await ask(mcp, llm, "Biggest orders in the south?")

    assert answer["privacy"]["results_sent"] is False
    assert "row-level" in answer["privacy"]["reason"]
    assert answer["summary"]["text"].startswith("3 rows.")
    assert len(llm.received) == 1  # only the SQL call


async def test_strict_mode_sends_only_the_schema(mcp, fake_llm):
    llm = fake_llm(json.dumps(BY_REGION))

    answer = await ask(mcp, llm, mode="strict")

    assert answer["privacy"]["results_sent"] is False
    assert "Highest total" in answer["summary"]["text"]
    assert [call["step"] for call in answer["done"]["audit"]] == ["write_sql"]


async def test_failed_sql_gets_one_fix_with_a_redacted_error(mcp, fake_llm):
    llm = fake_llm('{"sql": "SELECT regionx FROM self"}', json.dumps(BY_REGION), "fine")

    answer = await ask(mcp, llm)

    steps = [call["step"] for call in answer["done"]["audit"]]
    assert steps == ["write_sql", "fix_sql", "write_insights"]
    fix_payload = json.loads(answer["done"]["audit"][1]["user"])
    assert fix_payload["previous_sql"] == "SELECT regionx FROM self"
    assert "regionx" in fix_payload["error"]
    assert answer["table"]["row_count"] == 3


async def test_sql_that_fails_twice_ends_with_an_error_event(mcp, fake_llm):
    llm = fake_llm('{"sql": "DROP TABLE self"}', '{"sql": "DELETE FROM self"}')

    answer = await ask(mcp, llm)

    assert "Only SELECT" in answer["error"]["message"]
    assert "table" not in answer


async def test_a_reply_without_sql_is_an_error_event(mcp, fake_llm):
    answer = await ask(mcp, fake_llm("I cannot help with that."))
    assert answer["error"]["message"] == "The model did not return a SQL query"


async def test_no_dataset(upload_dir, fake_llm):
    answer = await ask(InProcessMcp(), fake_llm())
    assert answer["error"]["message"] == NO_DATASET_MESSAGE


async def test_events_put_the_table_before_the_insights(mcp, fake_llm):
    llm = fake_llm(json.dumps(BY_REGION), "one two three")
    events = [event["type"] async for event in answer_question("q", mcp, llm, "standard", 20)]
    assert events[:3] == ["sql", "table", "privacy"]
    assert events[3:] == ["insight", "insight", "insight", "done"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('conversion failed for 3 values: ["ann@x.com", "bo@y.com"]', "conversion failed for 3 values: […]"),
        ("first line\nsecond line", "first line"),
        ("", "unknown error"),
    ],
)
def test_redact_error(raw, expected):
    assert redact_error(raw) == expected

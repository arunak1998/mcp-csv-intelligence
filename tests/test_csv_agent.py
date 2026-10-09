from contextlib import asynccontextmanager

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from csv_intelligence.agents import csv_agent
from csv_intelligence.agents.connection import McpConnection
from csv_intelligence.agents.data_context import NO_FILE_MESSAGE


class ScriptedModel(GenericFakeChatModel):
    """Plays back a fixed list of AI messages and accepts tool bindings like a real chat model."""

    def bind_tools(self, tools, **kwargs):
        return self


@tool
def get_files_list() -> list[str]:
    """List files."""
    return ["data/sample_sales.csv"]


@tool
def get_schema(file_location: str) -> list[dict]:
    """Schema."""
    return [{"name": "revenue", "dtype": "Int64"}]


@tool
def execute_polars_sql(file_locations: list[str], query: str, file_type: str = "csv") -> list[dict]:
    """Run SQL."""
    return [{"total": 42}]


def patch_agent(monkeypatch, tools, replies):
    @asynccontextmanager
    async def fake_open(connection):
        yield tools

    monkeypatch.setattr(csv_agent, "open_mcp_tools", fake_open)
    monkeypatch.setattr(
        csv_agent, "create_llm", lambda *args, **kwargs: ScriptedModel(messages=iter(replies))
    )


CONNECTION = McpConnection("http://unused")


async def test_agent_runs_a_tool_then_answers_without_the_end_marker(monkeypatch):
    sql_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "execute_polars_sql",
                "args": {
                    "file_locations": ["data/sample_sales.csv"],
                    "query": "SELECT SUM(revenue) AS total FROM self",
                },
                "id": "call_1",
            }
        ],
    )
    patch_agent(
        monkeypatch,
        [get_files_list, get_schema, execute_polars_sql],
        [sql_call, AIMessage(content="📊 **Answer Summary**\nTotal revenue is 42.\nEND")],
    )

    answer = await csv_agent.run_csv_agent("total revenue?", CONNECTION)

    assert answer == "📊 **Answer Summary**\nTotal revenue is 42."


async def test_agent_short_circuits_when_no_file_is_present(monkeypatch):
    @tool
    def no_files() -> list[str]:
        """List files."""
        return []

    no_files.name = "get_files_list"
    patch_agent(monkeypatch, [no_files, get_schema], [])

    assert await csv_agent.run_csv_agent("anything", CONNECTION) == NO_FILE_MESSAGE

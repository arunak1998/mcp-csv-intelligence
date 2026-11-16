"""Shared fakes (LLM, MCP) and fixtures with the sample sales dataset."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from csv_intelligence.data.ingest import ingest_csv


class FakeLLM:
    """Returns canned replies in order and records the messages it was sent."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.received: list[list] = []

    async def ainvoke(self, messages):
        self.received.append(messages)
        return SimpleNamespace(content=self.replies.pop(0))

    async def astream(self, messages):
        """Streams the next reply word by word, like a chat model streaming tokens."""
        self.received.append(messages)
        for word in self.replies.pop(0).split(" "):
            yield SimpleNamespace(content=word + " ")


class InProcessMcp:
    """Stands in for McpClient by calling the real server tools directly (no HTTP)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        from csv_intelligence.agents.mcp_client import ToolCallError
        from csv_intelligence.server import analyst

        arguments = arguments or {}
        self.calls.append((tool, arguments))
        try:
            result = getattr(analyst, tool)(**arguments)
            return await result if hasattr(result, "__await__") else result
        except Exception as error:
            raise ToolCallError(str(error)) from error


@pytest.fixture
def fake_llm():
    return FakeLLM


SAMPLE_CSV = Path("data/sample_sales.csv")


@pytest.fixture
def upload_dir(tmp_path, monkeypatch) -> Path:
    """An empty upload folder that both the server and the ingest code use."""
    folder = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(folder))
    return folder


@pytest.fixture
def sales_dataset(upload_dir, tmp_path) -> str:
    """The sample sales CSV converted to a dataset; returns its name."""
    copy = tmp_path / "sample_sales.csv"
    shutil.copy(SAMPLE_CSV, copy)
    return ingest_csv(copy, upload_dir, "sample_sales.csv")["dataset"]


@pytest.fixture
def mcp(sales_dataset) -> InProcessMcp:
    """An MCP stand-in serving the sample sales dataset."""
    return InProcessMcp()

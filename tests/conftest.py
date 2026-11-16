"""Shared fakes: tools and LLMs that mimic the small slice of the LangChain API the agents use."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from csv_intelligence.data.ingest import ingest_csv


class FakeTool:
    def __init__(self, name: str, result=None, error: Exception | None = None):
        self.name = name
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def ainvoke(self, arguments: dict):
        self.calls.append(arguments)
        if self.error:
            raise self.error
        return self.result


class FakeLLM:
    """Returns canned replies in order and records the messages it was sent."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.received: list[list] = []

    async def ainvoke(self, messages):
        self.received.append(messages)
        return SimpleNamespace(content=self.replies.pop(0))


@pytest.fixture
def fake_tool():
    return FakeTool


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

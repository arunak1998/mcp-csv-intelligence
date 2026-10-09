"""Shared fakes: tools and LLMs that mimic the small slice of the LangChain API the agents use."""

from types import SimpleNamespace

import pytest


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

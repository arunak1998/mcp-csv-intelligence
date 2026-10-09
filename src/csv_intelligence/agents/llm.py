"""LLM factory shared by both agents. Works with OpenAI or any OpenAI-compatible gateway."""

import os

from langchain_openai import ChatOpenAI

from csv_intelligence.settings import DEFAULT_MODEL, require_env


def create_llm(**kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        api_key=require_env("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL") or None,
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or None,
        **kwargs,
    )

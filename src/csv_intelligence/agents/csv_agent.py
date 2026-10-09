"""Chat agent: answers natural-language questions about a CSV with a ReAct loop over MCP tools."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from csv_intelligence.agents.connection import McpConnection, open_mcp_tools
from csv_intelligence.agents.data_context import NO_FILE_MESSAGE, load_data_context
from csv_intelligence.agents.llm import create_llm
from csv_intelligence.agents.parsing import DataContext, strip_end_marker
from csv_intelligence.agents.prompts import CSV_ANALYST_PROMPT

logger = logging.getLogger(__name__)

# The prompt allows at most two tool calls; each costs two graph steps, plus the final answer.
RECURSION_LIMIT = 12
RECURSION_MESSAGE = "I could not finish this analysis within the step limit. Please try a simpler question."


def context_hook(data: DataContext):
    """Build a pre-model hook that tells the LLM which file and columns it is working with."""
    context = f"Data file: {data.file_path} | Columns: {', '.join(data.schema)}"

    def pre_model_hook(state: dict[str, Any]) -> dict[str, Any]:
        return {"llm_input_messages": [SystemMessage(content=f"CONTEXT: {context}"), *state["messages"]]}

    return pre_model_hook


async def run_csv_agent(question: str, connection: McpConnection) -> str:
    """Answer one question about the CSV the MCP server exposes."""
    async with open_mcp_tools(connection) as tools:
        data = await load_data_context(tools)
        if not data.file_path:
            return NO_FILE_MESSAGE
        logger.info("Analysing %s (%d columns)", data.file_path, len(data.schema))

        agent = create_react_agent(
            create_llm(),
            tools=tools,
            prompt=CSV_ANALYST_PROMPT,
            pre_model_hook=context_hook(data),
        )
        try:
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=question)]},
                config={"recursion_limit": RECURSION_LIMIT},
            )
        except GraphRecursionError:
            return RECURSION_MESSAGE
        return strip_end_marker(result["messages"][-1].content)

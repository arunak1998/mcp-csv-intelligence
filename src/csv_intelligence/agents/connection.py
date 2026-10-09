"""How agents reach the MCP server."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_LOCAL_URL = "http://localhost:8050/mcp"
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class McpConnection:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


def local_connection() -> McpConnection:
    return McpConnection(url=os.getenv("MCP_SERVER_URL", DEFAULT_LOCAL_URL))


@asynccontextmanager
async def open_mcp_tools(connection: McpConnection) -> AsyncIterator[list[BaseTool]]:
    """Open an MCP session and yield the server's tools as LangChain tools."""
    async with streamablehttp_client(connection.url, connection.headers, timeout=TIMEOUT_SECONDS) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield await load_mcp_tools(session)


def find_tool(tools: list[BaseTool], name: str) -> BaseTool:
    for tool in tools:
        if tool.name == name:
            return tool
    raise LookupError(f"MCP server does not expose a '{name}' tool")

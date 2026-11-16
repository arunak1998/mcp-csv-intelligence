"""One MCP session kept open and shared by every request, reconnecting if the server restarts."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5
RETRY_DELAY_SECONDS = 1
REQUEST_TIMEOUT_SECONDS = 120
# Longest a tool call may take. Queries are stopped server-side after QUERY_TIMEOUT_SECONDS (10 s by
# default), so this only ends calls whose reply can never arrive.
CALL_TIMEOUT_SECONDS = 60
TOOL_ERROR_PREFIX = re.compile(r"^Error executing tool \w+: ")


class McpUnavailableError(ConnectionError):
    """The MCP server could not be reached."""


class ToolCallError(RuntimeError):
    """The server ran the tool and reported an error (bad SQL, unknown dataset, timeout, ...)."""


def tool_result(result: Any) -> dict[str, Any]:
    """The tool's dict result. Every tool on our server returns a dict."""
    text = "\n".join(block.text for block in result.content if getattr(block, "text", None))
    if result.isError:
        raise ToolCallError(TOOL_ERROR_PREFIX.sub("", text).strip())
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(text)


class McpClient:
    """Holds a single MCP session in a background task.

    The session is entered and exited in that one task (anyio requires this), while any
    request may call tools on it concurrently. If the connection drops, calls waiting on it fail at
    once with McpUnavailableError (they would otherwise wait forever: the session is torn down in
    the background task, which can't wake a call made from another task), and the task reconnects.
    """

    def __init__(self, url: str):
        self.url = url
        self._session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._disconnect = asyncio.Event()
        self._closed = asyncio.Event()  # set when the current session ends; a new one per session
        self._stopping = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self._disconnect.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stopping:
            closed = asyncio.Event()
            try:
                async with streamablehttp_client(self.url, timeout=REQUEST_TIMEOUT_SECONDS) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._session, self._closed = session, closed
                        self._ready.set()
                        await self._disconnect.wait()
            except Exception as error:  # the server is down or went away; try again shortly
                logger.warning("MCP connection to %s failed: %s", self.url, error)
            finally:
                closed.set()
                self._session = None
                self._ready.clear()
                self._disconnect.clear()
            if not self._stopping:
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    async def _wait_for_session(self) -> ClientSession:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=CONNECT_TIMEOUT_SECONDS)
        except TimeoutError as error:
            raise McpUnavailableError(
                f"The MCP server is not reachable at {self.url}. Start it with: csv-mcp-server"
            ) from error
        assert self._session is not None
        return self._session

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a tool; fails fast if the session ends, and after CALL_TIMEOUT_SECONDS at most."""
        session, closed = await self._wait_for_session(), self._closed
        call = asyncio.ensure_future(session.call_tool(tool, arguments or {}))
        lost = asyncio.ensure_future(closed.wait())
        try:
            done, _ = await asyncio.wait(
                {call, lost}, timeout=CALL_TIMEOUT_SECONDS, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            lost.cancel()
            if not call.done():
                call.cancel()
        if call in done and not call.cancelled():
            if call.exception() is None:
                return tool_result(call.result())
            reason = str(call.exception())
        elif closed.is_set():
            reason = "the server stopped"
        else:
            reason = f"no reply within {CALL_TIMEOUT_SECONDS}s"
        self._disconnect.set()  # reconnect for the next call
        raise McpUnavailableError(f"Lost the connection to the MCP server ({reason}).")


@asynccontextmanager
async def connected_client(url: str) -> AsyncIterator[McpClient]:
    """A started McpClient for scripts and tests; long-running apps call start()/stop() themselves."""
    client = McpClient(url)
    await client.start()
    try:
        yield client
    finally:
        await client.stop()

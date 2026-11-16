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
TOOL_ERROR_PREFIX = re.compile(r"^Error executing tool \w+: ")


class McpUnavailableError(ConnectionError):
    """The MCP server could not be reached."""


class ToolCallError(RuntimeError):
    """The server ran the tool and reported an error (bad SQL, unknown dataset, timeout, ...)."""


def root_cause(error: BaseException) -> BaseException:
    """The first underlying error inside (possibly nested) exception groups."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


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
    request may call tools on it concurrently. If a call fails because the connection
    dropped, the task reconnects and the next call uses the new session.
    """

    def __init__(self, url: str):
        self.url = url
        self._session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._disconnect = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task | None = None
        self._reported_failure = False

    @property
    def connected(self) -> bool:
        return self._ready.is_set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self._disconnect.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stopping:
            try:
                async with streamablehttp_client(self.url, timeout=REQUEST_TIMEOUT_SECONDS) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._session = session
                        self._ready.set()
                        self._reported_failure = False
                        logger.info("Connected to the MCP server at %s", self.url)
                        await self._disconnect.wait()
            except Exception as error:  # the server is down or went away; try again shortly
                self._report_failure(error)
            finally:
                self._session = None
                self._ready.clear()
                self._disconnect.clear()
            if not self._stopping:
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    def _report_failure(self, error: BaseException) -> None:
        """Warn once per outage with the real cause; repeat attempts are logged at debug level."""
        level = logging.DEBUG if self._reported_failure else logging.WARNING
        logger.log(
            level,
            "MCP server at %s is not reachable (%s); retrying every %ss",
            self.url,
            root_cause(error),
            RETRY_DELAY_SECONDS,
        )
        self._reported_failure = True

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
        session = await self._wait_for_session()
        try:
            result = await session.call_tool(tool, arguments or {})
        except Exception as error:
            self._disconnect.set()  # reconnect for the next call
            raise McpUnavailableError(f"Lost the connection to the MCP server: {error}") from error
        return tool_result(result)


@asynccontextmanager
async def connected_client(url: str) -> AsyncIterator[McpClient]:
    """A started McpClient for scripts and tests; long-running apps call start()/stop() themselves."""
    client = McpClient(url)
    await client.start()
    try:
        yield client
    finally:
        await client.stop()

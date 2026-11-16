"""The persistent MCP client against the real server, served over HTTP in a background thread."""

import socket
import threading
import time

import pytest
import uvicorn

from csv_intelligence.agents.mcp_client import McpClient, McpUnavailableError, ToolCallError, connected_client
from csv_intelligence.server import analyst


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """FastMCP's session manager runs once per process, so one server serves the whole module."""
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(analyst.mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def test_one_session_serves_many_calls(server_url, sales_dataset):
    async with connected_client(server_url) as client:
        assert await client.call("list_datasets") == {"datasets": ["sample_sales"]}
        profile = await client.call("get_schema", {"dataset": sales_dataset})
        assert profile["row_count"] == 120
        first_session = client._session

        result = await client.call(
            "run_sql", {"dataset": sales_dataset, "query": "SELECT COUNT(*) AS n FROM self"}
        )
        assert result["rows"] == [[120]]
        assert client._session is first_session


async def test_calls_can_run_concurrently_on_one_session(server_url, sales_dataset):
    import asyncio

    async with connected_client(server_url) as client:
        queries = [f"SELECT COUNT(*) AS n FROM self WHERE units > {units}" for units in range(5)]
        results = await asyncio.gather(
            *(client.call("run_sql", {"dataset": sales_dataset, "query": query}) for query in queries)
        )
    counts = [result["rows"][0][0] for result in results]
    assert counts == sorted(counts, reverse=True) and counts[0] == 120


async def test_tool_errors_are_raised_with_the_server_message(server_url, sales_dataset):
    async with connected_client(server_url) as client:
        with pytest.raises(ToolCallError, match="^Only SELECT queries are allowed"):
            await client.call("run_sql", {"dataset": sales_dataset, "query": "DROP TABLE self"})
        # the session survives a tool error
        assert (await client.call("list_datasets"))["datasets"] == ["sample_sales"]


async def test_unreachable_server_gives_a_clear_error(monkeypatch):
    from csv_intelligence.agents import mcp_client

    monkeypatch.setattr(mcp_client, "CONNECT_TIMEOUT_SECONDS", 0.3)
    client = McpClient(f"http://127.0.0.1:{free_port()}/mcp")
    await client.start()
    try:
        with pytest.raises(McpUnavailableError, match="csv-mcp-server"):
            await client.call("list_datasets")
    finally:
        await client.stop()

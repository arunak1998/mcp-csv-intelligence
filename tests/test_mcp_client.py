"""The persistent MCP client against the real server, served over HTTP in a background thread."""

import os
import socket
import subprocess
import sys
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


async def test_an_outage_is_reported_once_with_its_real_cause(monkeypatch, caplog):
    import asyncio
    import logging

    from csv_intelligence.agents import mcp_client

    monkeypatch.setattr(mcp_client, "RETRY_DELAY_SECONDS", 0.05)
    client = McpClient(f"http://127.0.0.1:{free_port()}/mcp")
    with caplog.at_level(logging.WARNING, logger=mcp_client.__name__):
        await client.start()
        await asyncio.sleep(0.6)
        await client.stop()
    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1
    assert "not reachable" in warnings[0] and "TaskGroup" not in warnings[0]


def test_root_cause_unwraps_exception_groups():
    from csv_intelligence.agents.mcp_client import root_cause

    inner = ConnectionError("refused")
    assert root_cause(ExceptionGroup("outer", [ExceptionGroup("inner", [inner])])) is inner
    assert root_cause(inner) is inner


def start_server_process(port: int, upload_dir) -> subprocess.Popen:
    """The real csv-mcp-server in its own process, so the test can kill and restart it."""
    env = {**os.environ, "MCP_PORT": str(port), "UPLOAD_DIR": str(upload_dir)}
    process = subprocess.Popen(
        [sys.executable, "-m", "csv_intelligence.server.analyst"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return process
        time.sleep(0.2)
    process.kill()
    raise RuntimeError("MCP server did not start")


async def test_calls_fail_fast_when_the_server_dies_and_recover_after_restart(
    sales_dataset, upload_dir, monkeypatch
):
    import asyncio

    from csv_intelligence.agents import mcp_client

    monkeypatch.setattr(mcp_client, "RETRY_DELAY_SECONDS", 0.2)
    port = free_port()
    server = await asyncio.to_thread(start_server_process, port, upload_dir)
    client = McpClient(f"http://127.0.0.1:{port}/mcp")
    await client.start()
    try:
        assert (await client.call("list_datasets"))["datasets"] == ["sample_sales"]

        server.kill()
        server.wait()
        started = time.monotonic()
        with pytest.raises(McpUnavailableError):
            await client.call("list_datasets")
        assert time.monotonic() - started < 10  # fails fast instead of waiting for a reply that never comes

        server = await asyncio.to_thread(start_server_process, port, upload_dir)
        deadline = time.monotonic() + 30
        while True:
            try:
                assert (await client.call("list_datasets"))["datasets"] == ["sample_sales"]
                break
            except McpUnavailableError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.2)
    finally:
        await client.stop()
        server.kill()
        server.wait()


async def test_a_call_that_never_gets_a_reply_times_out(monkeypatch):
    import asyncio

    from csv_intelligence.agents import mcp_client

    class SilentSession:
        async def call_tool(self, name, arguments):
            await asyncio.sleep(3600)

    monkeypatch.setattr(mcp_client, "CALL_TIMEOUT_SECONDS", 0.1)
    client = McpClient("http://unused")
    client._session = SilentSession()
    client._ready.set()

    with pytest.raises(McpUnavailableError, match="no reply within 0.1s"):
        await client.call("list_datasets")
    assert client._disconnect.is_set()  # the background task will reconnect

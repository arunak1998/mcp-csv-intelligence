import socket

from csv_intelligence.ui.health import mcp_server_is_up


def test_reports_up_when_something_is_listening(monkeypatch):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{server.getsockname()[1]}/mcp")
        assert mcp_server_is_up()


def test_reports_down_when_nothing_is_listening(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{free_port}/mcp")
    assert not mcp_server_is_up()

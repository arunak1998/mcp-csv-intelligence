"""Check that the MCP server is reachable, so the UI can say so instead of failing mid-question."""

import socket
from urllib.parse import urlparse

from csv_intelligence.agents.connection import local_connection


def mcp_server_is_up(timeout: float = 0.5) -> bool:
    url = urlparse(local_connection().url)
    try:
        with socket.create_connection((url.hostname, url.port or 80), timeout=timeout):
            return True
    except OSError:
        return False

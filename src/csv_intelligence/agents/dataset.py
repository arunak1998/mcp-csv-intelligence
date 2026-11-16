"""Find the active dataset and its cached profile through the MCP server."""

from typing import Any

from csv_intelligence.agents.mcp_client import McpClient

NO_DATASET_MESSAGE = "No file is loaded, so there is nothing to analyze. Upload a CSV first."


async def active_dataset(mcp: McpClient) -> tuple[str, dict[str, Any]] | None:
    """(name, profile) of the dataset the server exposes, or None when nothing is uploaded."""
    names = (await mcp.call("list_datasets"))["datasets"]
    if not names:
        return None
    return names[0], await mcp.call("get_schema", {"dataset": names[0]})

"""Discover the active CSV file and its schema through the MCP server."""

from langchain_core.tools import BaseTool

from csv_intelligence.agents.connection import find_tool
from csv_intelligence.agents.parsing import DataContext, parse_file_list, parse_schema

NO_FILE_MESSAGE = "**No file is present and there is nothing to analyze.**"


async def load_data_context(tools: list[BaseTool]) -> DataContext:
    """Return the first file the server exposes and its schema (empty when there is no file)."""
    files = parse_file_list(await find_tool(tools, "get_files_list").ainvoke({}))
    if not files:
        return DataContext(file_path="", schema={})

    raw_schema = await find_tool(tools, "get_schema").ainvoke({"file_location": files[0]})
    return DataContext(file_path=files[0], schema=parse_schema(raw_schema))

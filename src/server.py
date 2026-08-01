import json
import uuid

"""
Entry point for the MCP server.
Provides the handlers for listing tools and for calling them.
"""


import anyio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from logger import get_logger
from request_processor.handler import handle_request
from tools import API_SPECS, TOOLS
from utils.payload import build_payload

logger = get_logger(__name__)


server = Server("mlit-geospatial-mcp")


@server.list_tools()
async def handle_list_tools():
    """
    Return the list of available tools.

    Returns:
        TOOLS: the list of tool definitions
    """
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    Run a tool called by Claude.

    Looks up the API_SPEC by tool name, converts the arguments into an API payload, passes it
    to handle_request (internal processing), and returns the result as JSON.

    Args:
        name(str): the name of the tool that was called
        arguments(dict): the arguments passed to the tool

    Returns:
        list[TextContent]: the result (a JSON string)
    """
    rid = uuid.uuid4().hex
    logger.info("Tool called", tool=name, request_id=rid)

    spec = API_SPECS[name]
    payload = build_payload(
        spec=spec,
        args=arguments,
    )
    logger.info("Tool payload", payload=payload)
    result = await handle_request(payload)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


async def _main() -> None:
    """
    Main entry point for the MCP server.
    Runs the event loop.
    """
    async with stdio_server() as (read, write):
        caps = server.get_capabilities(
            notification_options=NotificationOptions(), experimental_capabilities={}
        )

        init_opts = InitializationOptions(
            server_name="mlit-geospatial-mcp", server_version="0.1.0", capabilities=caps
        )

        logger.info("MCP server starting...")
        await server.run(read, write, init_opts)


if __name__ == "__main__":
    anyio.run(_main)

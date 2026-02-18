import json
import logging
import uuid

"""
MCPサーバーのエントリポイント。
ツールのリスト取得やツール呼び出しのハンドラを提供する。
"""


import anyio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from request_processor.handler import handle_request
from tools import API_SPECS, TOOLS
from utils.payload import build_payload
from utils.space_id_calculaton import spatial_id_from_wgs84

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


server = Server("mlit-geospatial-mcp")


@server.list_tools()
async def handle_list_tools():
    """
    利用可能なツール一覧を取得する。

    Returns:
        TOOLS:ツール定義のリスト
    """
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    Claudから呼び出されたtoolを実行する。
    tool名からAPI_SPECを取得し、引数をAPI用のpayloadに変換後、
    handle_request（内部処理）に渡す。
    結果をJSONとして返却。

    Args:
        name(str):呼び出されたtool名
        arguments(dict):toolに渡された引数

    Returns:
        list[TextContent]: 実行結果（JSON文字列）
    """
    rid = uuid.uuid4().hex
    logger.info(f"Tool called: {name} (request_id: {rid})")

    # 空間ID計算ツールの場合（PLATEAUデータ取得）
    if name == "plateau_space_id":
        lat = arguments["lat"]
        lon = arguments["lon"]
        z = arguments.get("z", 18)
        h_m = arguments.get("h_m", 0.0)
        sid = spatial_id_from_wgs84(lat, lon, z, h_m)
        result = {
            "spatial_id": sid.as_string(),
            "components": {"z": sid.z, "f": sid.f, "x": sid.x, "y": sid.y},
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            )
        ]

    spec = API_SPECS[name]
    payload = build_payload(
        spec=spec,
        args=arguments,
    )
    logger.info(f"payload:{payload}")
    result = await handle_request(payload)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


async def _main() -> None:
    """
    MCPサーバーのメイン処理。
    イベントループを実行する。
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

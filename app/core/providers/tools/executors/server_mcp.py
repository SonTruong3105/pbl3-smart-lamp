"""ServerMCPExecutor — gọi tool từ MCP server phía server."""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from app.core.providers.tools.executors.base import ToolExecutor
from app.core.providers.tools.unified.register import Action, ActionResponse

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client as streamablehttp
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


_MCP_CONFIG = Path("data/.mcp_server_settings.json")


def _load_mcp_config() -> dict:
    if _MCP_CONFIG.exists():
        try:
            return json.loads(_MCP_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


class ServerMCPExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        if not HAS_MCP:
            return ActionResponse(
                Action.ERROR,
                result="Chưa cài mcp SDK. Chạy: pip install mcp",
            )

        cfg = _load_mcp_config()
        servers = cfg.get("mcpServers", {})
        if not servers:
            return ActionResponse(
                Action.ERROR,
                result="Chưa cấu hình MCP server (data/.mcp_server_settings.json).",
            )

        # Lấy server đầu tiên (có thể mở rộng map tool -> server)
        server_name, server_cfg = next(iter(servers.items()))
        url = server_cfg.get("url")
        if not url:
            return ActionResponse(Action.ERROR, result=f"MCP server '{server_name}' thiếu url.")

        actual_name = tool_name[4:] if tool_name.startswith("mcp_") else tool_name

        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as http_client:
                async with streamablehttp(url, http_client=http_client) as streams:
                    read, write = streams[0], streams[1]
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(actual_name, arguments)
                        text = "\n".join(
                            item.text for item in result.content
                            if hasattr(item, "text") and item.text
                        )
                        return ActionResponse(Action.REQLLM, result=text or str(result))
        except Exception as e:
            logger.exception(f"ServerMCPExecutor lỗi: {e}")
            return ActionResponse(Action.ERROR, result=f"MCP lỗi: {e}")

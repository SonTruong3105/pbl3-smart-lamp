"""Tool executors — gộp từ 5 file cũ (base, server_plugin, server_mcp,
device_iot, device_mcp, mcp_endpoint).

Mỗi executor triển khai interface ToolExecutor.execute(conn, tool_name, arguments).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from app.core.providers.tools.unified.register import (
    Action,
    ActionResponse,
    all_function_registry,
)
from app.core.providers.tools.context import set_connection, reset_connection
from app.core.providers.tools.device_mcp_manager import (
    device_tool_prefix,
    get_device_mcp_manager,
)


# ─── MCP SDK optional ────────────────────────────────────────────────
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


# ─── Base ─────────────────────────────────────────────────────────────
class ToolExecutor(ABC):
    """Interface mà mọi executor phải triển khai."""

    @abstractmethod
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        ...


# ─── Server Plugin (Python function registry) ─────────────────────────
class ServerPluginExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        item = all_function_registry.get(tool_name)
        if not item:
            return ActionResponse(
                Action.NOTFOUND,
                result=f"Không có tool '{tool_name}'.",
            )
        context_token = set_connection(conn)
        try:
            result = await item.func(**arguments)
            if isinstance(result, ActionResponse):
                return result
            return ActionResponse(Action.REQLLM, result=str(result))
        except TypeError as e:
            return ActionResponse(Action.ERROR, result=f"Tham số sai: {e}")
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"Lỗi: {e}")
        finally:
            reset_connection(context_token)


# ─── Server MCP (MCP server phía server) ──────────────────────────────
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
        server_name, server_cfg = next(iter(servers.items()))
        url = server_cfg.get("url")
        if not url:
            return ActionResponse(
                Action.ERROR,
                result=f"MCP server '{server_name}' thiếu url.",
            )
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
                        return ActionResponse(
                            Action.REQLLM, result=text or str(result),
                        )
        except Exception as e:
            logger.exception(f"ServerMCPExecutor lỗi: {e}")
            return ActionResponse(Action.ERROR, result=f"MCP lỗi: {e}")


# ─── Device MCP (qua DeviceMCPManager) ────────────────────────────────
class DeviceMCPExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        manager = get_device_mcp_manager()
        device_id = getattr(conn, "device_id", None)
        if not device_id:
            return ActionResponse(
                Action.ERROR, result="Không xác định được thiết bị.",
            )
        prefix = device_tool_prefix(device_id)
        actual_name = (
            tool_name[len(prefix):]
            if tool_name.startswith(prefix)
            else tool_name
        )
        return await manager.call_tool(device_id, actual_name, arguments)


# ─── MCP Endpoint (MCP ngoài) ─────────────────────────────────────────
class MCPEndpointExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        handler = getattr(conn, "mcp_endpoint_handler", None)
        if handler is None:
            return ActionResponse(
                Action.ERROR,
                result="Chưa cấu hình MCP endpoint.",
            )
        try:
            result = await handler.call_tool(tool_name, arguments)
            return ActionResponse(Action.REQLLM, result=str(result))
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"MCP endpoint lỗi: {e}")


__all__ = [
    "ToolExecutor",
    "ServerPluginExecutor",
    "ServerMCPExecutor",
    "DeviceMCPExecutor",
    "MCPEndpointExecutor",
]
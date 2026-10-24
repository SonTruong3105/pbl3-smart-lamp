"""MCPEndpointExecutor — gọi tool từ MCP endpoint bên ngoài."""
from typing import Any, Dict

from app.core.providers.tools.executors.base import ToolExecutor
from app.core.providers.tools.unified.register import Action, ActionResponse


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

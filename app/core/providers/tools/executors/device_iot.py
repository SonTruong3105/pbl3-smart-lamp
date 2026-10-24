"""DeviceIoTExecutor — thực thi tool IoT được thiết bị báo cáo."""
from typing import Any, Dict

from app.core.providers.tools.executors.base import ToolExecutor
from app.core.providers.tools.unified.register import Action, ActionResponse


class DeviceIoTExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        # Gửi lệnh MCP xuống thiết bị qua transport
        try:
            payload = {
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            }
            transport = getattr(conn, "transport", None) or getattr(conn, "ws", None)
            if transport is None:
                return ActionResponse(Action.ERROR, result="Không có transport.")
            await transport.send_json(payload)
            return ActionResponse(
                Action.RECORD,
                result=f"Đã gửi lệnh {tool_name} xuống thiết bị.",
            )
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"Lỗi gửi IoT: {e}")

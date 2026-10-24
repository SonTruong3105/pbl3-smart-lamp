"""DeviceMCPExecutor — gọi tool MCP từ thiết bị (đúng chuẩn server gốc)."""
from typing import Any, Dict

from app.core.providers.tools.executors.base import ToolExecutor
from app.core.providers.tools.unified.register import Action, ActionResponse
from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager


class DeviceMCPExecutor(ToolExecutor):
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        manager = get_device_mcp_manager()
        device_id = getattr(conn, "device_id", None)
        if not device_id:
            return ActionResponse(Action.ERROR, result="Không xác định được thiết bị.")

        # Lấy tên tool gốc (bỏ prefix)
        prefix = f"dev_{device_id[:8]}_"
        actual_name = tool_name[len(prefix):] if tool_name.startswith(prefix) else tool_name

        return await manager.call_tool(device_id, actual_name, arguments)

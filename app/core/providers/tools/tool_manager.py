"""ToolManager — đăng ký executor và điều phối thực thi tool theo ToolType."""
from typing import Any, Dict, Optional

from loguru import logger

from app.core.providers.tools.unified.register import ToolType
from app.core.providers.tools.executors import (
    ToolExecutor,
    ServerPluginExecutor,
    ServerMCPExecutor,
    DeviceIoTExecutor,
    DeviceMCPExecutor,
    MCPEndpointExecutor,
)


class ToolManager:
    def __init__(self):
        self._executors: Dict[ToolType, ToolExecutor] = {
            ToolType.WAIT: ServerPluginExecutor(),
            ToolType.IOT_CTL: DeviceIoTExecutor(),
            ToolType.MCP_CLIENT: ServerMCPExecutor(),
            ToolType.SYSTEM_CTL: ServerPluginExecutor(),
            ToolType.CHANGE_SYS_PROMPT: ServerPluginExecutor(),
        }
        # Tool có tên bắt đầu bằng `dev_` → route sang DeviceMCPExecutor
        self._device_mcp_executor = DeviceMCPExecutor()
        # Lưu ý: routing theo tên được xử lý trong execute_tool() bên dưới
        # Mặc định map cho device MCP / endpoint nếu cần
        self._executors.setdefault(ToolType.MCP_CLIENT, ServerMCPExecutor())

    def register(self, tool_type: ToolType, executor: ToolExecutor):
        self._executors[tool_type] = executor

    def get_executor(self, tool_type: ToolType) -> Optional[ToolExecutor]:
        return self._executors.get(tool_type)

    async def execute_tool(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any],
        tool_type: ToolType = ToolType.WAIT,
    ):
        # Nếu tên tool bắt đầu bằng `dev_` → đây là tool từ thiết bị
        if tool_name.startswith("dev_"):
            return await self._device_mcp_executor.execute(conn, tool_name, arguments)

        executor = self._executors.get(tool_type)
        if executor is None:
            logger.warning(f"Không có executor cho ToolType={tool_type}")
            from app.core.providers.tools.unified.register import Action, ActionResponse
            return ActionResponse(Action.NOTFOUND, result=f"Không hỗ trợ ToolType {tool_type}")
        return await executor.execute(conn, tool_name, arguments)

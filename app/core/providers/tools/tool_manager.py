"""ToolManager — đăng ký executor và điều phối thực thi tool theo ToolType."""
from typing import Any, Dict, Optional

from loguru import logger

from app.core.providers.tools.unified.register import Action, ActionResponse, ToolType
from app.core.providers.tools.executors import (
    ToolExecutor,
    ServerPluginExecutor,
    ServerMCPExecutor,
    DeviceMCPExecutor,
)


class ToolManager:
    def __init__(self):
        self._executors: Dict[ToolType, ToolExecutor] = {
            ToolType.WAIT: ServerPluginExecutor(),
            ToolType.MCP_CLIENT: ServerMCPExecutor(),
            ToolType.SYSTEM_CTL: ServerPluginExecutor(),
            ToolType.CHANGE_SYS_PROMPT: ServerPluginExecutor(),
        }
        self._device_mcp_executor = DeviceMCPExecutor()

    def register(self, tool_type: ToolType, executor: ToolExecutor):
        self._executors[tool_type] = executor

    def get_executor(self, tool_type: ToolType) -> Optional[ToolExecutor]:
        return self._executors.get(tool_type)

    async def execute_tool(
        self,
        conn: Any,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_type: ToolType = ToolType.WAIT,
        is_device_tool: bool = False,
    ):
        if is_device_tool or tool_name.startswith("dev_"):
            return await self._device_mcp_executor.execute(conn, tool_name, arguments)

        executor = self._executors.get(tool_type)
        if executor is None:
            logger.warning(f"Không có executor cho ToolType={tool_type}")
            return ActionResponse(
                Action.NOTFOUND, result=f"Không hỗ trợ ToolType {tool_type}"
            )
        return await executor.execute(conn, tool_name, arguments)

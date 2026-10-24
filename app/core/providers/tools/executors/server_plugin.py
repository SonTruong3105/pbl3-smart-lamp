"""ServerPluginExecutor — thực thi tool từ registry Python function."""
from typing import Any, Dict

from app.core.providers.tools.executors.base import ToolExecutor
from app.core.providers.tools.unified.register import (
    Action, ActionResponse, all_function_registry,
)


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
        try:
            result = await item.func(**arguments)
            if isinstance(result, ActionResponse):
                return result
            return ActionResponse(Action.REQLLM, result=str(result))
        except TypeError as e:
            return ActionResponse(Action.ERROR, result=f"Tham số sai: {e}")
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"Lỗi: {e}")

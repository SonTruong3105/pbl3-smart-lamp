"""UnifiedToolHandler — điều phối thực thi tool qua ToolManager."""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from loguru import logger

from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
from app.core.providers.tools.tool_manager import ToolManager
from app.core.providers.tools.unified.register import (
    Action, ActionResponse, all_function_registry,
)


class UnifiedToolHandler:
    def __init__(self, log=None):
        self.log = log or logger
        self._display_callback = None
        self.tool_manager = ToolManager()

    def set_display_callback(self, callback):
        self._display_callback = callback

    async def execute(
        self, conn: Any, name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        device_id = getattr(conn, "device_id", None)
        dev_item = get_device_mcp_manager().get_function_item(device_id, name)
        item = dev_item or all_function_registry.get(name)
        if item is None:
            self.log.warning(f"Tool không tồn tại: {name} (device_id={device_id})")
            return ActionResponse(Action.NOTFOUND, result=f"Không có tool '{name}'.")

        if self._display_callback:
            try:
                await self._display_callback(name)
            except Exception:
                pass

        try:
            timeout = 180.0 if name == "play_music" else 10.0
            result = await asyncio.wait_for(
                self.tool_manager.execute_tool(
                    conn,
                    name,
                    arguments,
                    tool_type=item.type,
                    is_device_tool=dev_item is not None,
                ),
                timeout=timeout,
            )
            if isinstance(result, ActionResponse):
                return result
            return ActionResponse(Action.REQLLM, result=str(result))
        except asyncio.TimeoutError:
            self.log.error(f"Tool {name} timeout sau {timeout:.0f}s")
            return ActionResponse(Action.ERROR, result=f"Tool {name} quá thời gian chờ.")
        except Exception as e:
            self.log.exception(f"Tool {name} lỗi")
            return ActionResponse(Action.ERROR, result=f"Lỗi khi chạy {name}: {e}")

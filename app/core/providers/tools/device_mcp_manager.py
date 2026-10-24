"""DeviceMCPManager — quản lý tool MCP động theo từng thiết bị.

Đúng như server gốc: khi ESP32 gửi `tools/list`, manager đăng ký các tool
vào `all_function_registry` với ToolType.DEVICE_MCP và prefix `dev_`.
Khi ngắt kết nối, manager gỡ các tool của thiết bị đó.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from loguru import logger

from app.core.providers.tools.unified.register import (
    Action, ActionResponse, FunctionItem, ToolType, all_function_registry,
)


class DeviceMCPManager:
    """Quản lý tool MCP theo từng device_id."""

    def __init__(self):
        # device_id -> set(tên tool gốc do ESP32 khai báo)
        self._device_tools: Dict[str, Set[str]] = {}
        # device_id -> future đang chờ reply tools/call
        self._pending_futures: Dict[str, Dict[int, asyncio.Future]] = {}
        # device_id -> transport để gửi lệnh xuống
        self._transports: Dict[str, Any] = {}
        # request_id tăng dần
        self._req_id = 0

    def attach(self, device_id: str, transport: Any):
        """Gắn transport khi thiết bị kết nối."""
        self._transports[device_id] = transport
        self._pending_futures.setdefault(device_id, {})

    def detach(self, device_id: str):
        """Gỡ transport và tool khi thiết bị ngắt kết nối."""
        self._transports.pop(device_id, None)
        self._pending_futures.pop(device_id, None)
        self.unregister_device_tools(device_id)

    async def register_device_tools(self, device_id: str, tools: list):
        """Đăng ký tool do ESP32 báo qua `tools/list`."""
        names: Set[str] = set()
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if not name:
                continue
            # Prefix để tránh đụng với plugin cục bộ
            prefix = f"dev_{device_id[:8]}_"
            fq_name = prefix + name

            description = t.get("description", "")
            input_schema = t.get("inputSchema", {}) or {}

            # Tạo function wrapper
            async def _wrapper(_device_id=device_id, _tool_name=name, **kwargs):
                return await self.call_tool(_device_id, _tool_name, kwargs)

            all_function_registry[fq_name] = FunctionItem(
                name=fq_name,
                description=f"[Thiết bị] {description}",
                func=_wrapper,
                type=ToolType.MCP_CLIENT,  # tạm, sẽ route qua DeviceMCPExecutor
                parameters=input_schema,
            )
            names.add(fq_name)

        self._device_tools[device_id] = names
        logger.info(f"📡 DeviceMCP: đăng ký {len(names)} tool từ {device_id}")

    def unregister_device_tools(self, device_id: str):
        """Gỡ tool của thiết bị khỏi registry."""
        names = self._device_tools.pop(device_id, set())
        for n in names:
            all_function_registry.pop(n, None)
        if names:
            logger.info(f"📡 DeviceMCP: gỡ {len(names)} tool của {device_id}")

    def handle_mcp_message(self, device_id: str, payload: dict):
        """Xử lý message MCP nhận từ ESP32 (reply cho tools/call)."""
        msg_id = payload.get("id")
        if msg_id is None:
            return
        futs = self._pending_futures.get(device_id, {})
        fut = futs.pop(msg_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    async def call_tool(
        self, device_id: str, tool_name: str, arguments: dict,
        timeout: float = 10.0,
    ) -> ActionResponse:
        """Gửi `tools/call` xuống ESP32 và chờ reply."""
        transport = self._transports.get(device_id)
        if transport is None:
            return ActionResponse(
                Action.ERROR,
                result=f"Thiết bị {device_id} chưa kết nối.",
            )

        self._req_id += 1
        req_id = self._req_id
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_futures.setdefault(device_id, {})[req_id] = fut

        try:
            await transport.send_json({
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            })
            reply = await asyncio.wait_for(fut, timeout=timeout)
            return ActionResponse(Action.REQLLM, result=str(reply.get("result", reply)))
        except asyncio.TimeoutError:
            return ActionResponse(
                Action.ERROR,
                result=f"Thiết bị {device_id} không phản hồi sau {timeout}s.",
            )
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"Lỗi gửi MCP: {e}")
        finally:
            self._pending_futures.get(device_id, {}).pop(req_id, None)


# Singleton
_manager: Optional[DeviceMCPManager] = None


def get_device_mcp_manager() -> DeviceMCPManager:
    global _manager
    if _manager is None:
        _manager = DeviceMCPManager()
    return _manager

"""DeviceMCPManager — quản lý tool MCP động theo từng thiết bị (1 luồng WS)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Set

from loguru import logger

from app.core.providers.tools.unified.register import (
    Action, ActionResponse, FunctionItem, ToolType,
)


def _extract_mcp_result_payload(reply: dict) -> Any:
    """Trích xuất dữ liệu chuẩn từ JSON-RPC result của MCP (không bọc str thô)."""
    res = reply.get("result")
    if not isinstance(res, dict):
        return res if res is not None else reply
    content = res.get("content")
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                txt = item.get("text", "")
                try:
                    return json.loads(txt)
                except Exception:
                    texts.append(txt)
        if texts:
            return "\n".join(texts)
    return res


def device_tool_prefix(device_id: str) -> str:
    """Tên prefix ổn định, duy nhất cho tool của từng thiết bị (legacy helper)."""
    mac_clean = device_id.replace(":", "").replace("-", "").lower()
    return f"dev_{mac_clean}_"


class DeviceMCPManager:
    """Quản lý tool MCP theo từng device_id qua 1 transport duy nhất."""

    def __init__(self):
        # device_id -> {tool_name: FunctionItem} (cách ly hoàn toàn theo từng thiết bị)
        self._device_tools: Dict[str, Dict[str, FunctionItem]] = {}
        # device_id -> future đang chờ reply tools/call
        self._pending_futures: Dict[str, Dict[int, asyncio.Future]] = {}
        # device_id -> transport WS chính (/xiaozhi/v1/)
        self._transports: Dict[str, Any] = {}
        self._req_id = 0

    def attach(self, device_id: str, transport: Any, channel: str = "audio"):
        """Gắn transport khi thiết bị kết nối."""
        _ = channel
        self._transports[device_id] = transport
        self._pending_futures.setdefault(device_id, {})

    def detach(
        self,
        device_id: str,
        channel: Optional[str] = None,
        transport: Any = None,
    ):
        """Gỡ transport khi ngắt kết nối; chỉ gỡ tool nếu transport khớp."""
        _ = channel
        current = self._transports.get(device_id)
        if transport is not None and current is not transport:
            return
        self._transports.pop(device_id, None)
        self._pending_futures.pop(device_id, None)
        # Keep the last discovered schemas across transient disconnects. The tool
        # wrappers resolve the current transport at call time, and reconnecting
        # devices can use their cached schemas before rediscovery completes.

    def _get_transport(self, device_id: str, prefer_control: bool = True) -> Any:
        _ = prefer_control
        transport = self._transports.get(device_id)
        if transport is not None and getattr(transport, "is_connected", True):
            return transport
        return None

    def has_control_channel(self, device_id: str) -> bool:
        return self._get_transport(device_id) is not None

    def get_online_device_ids(self) -> Set[str]:
        return {
            did for did, tr in self._transports.items()
            if tr is not None and getattr(tr, "is_connected", True)
        }

    def online_device_ids(self) -> Set[str]:
        return self.get_online_device_ids()

    def get_device_tools(self, device_id: Optional[str]) -> Dict[str, FunctionItem]:
        if not device_id:
            return {}
        return dict(self._device_tools.get(device_id, {}))

    def get_function_item(
        self, device_id: Optional[str], tool_name: str
    ) -> Optional[FunctionItem]:
        if not device_id or not tool_name:
            return None
        return self._device_tools.get(device_id, {}).get(tool_name)

    def get_openai_tools(self, device_id: Optional[str]) -> list:
        tools = []
        for item in self.get_device_tools(device_id).values():
            tools.append({
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            })
        return tools

    async def register_device_tools(self, device_id: str, tools: list):
        """Đăng ký tool do ESP32 báo qua `tools/list` vào scope riêng của thiết bị."""
        device_map: Dict[str, FunctionItem] = {}
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if not name:
                continue

            description = t.get("description", "")
            raw_schema = t.get("inputSchema", {})
            if isinstance(raw_schema, dict):
                input_schema = dict(raw_schema)
                input_schema.setdefault("type", "object")
                input_schema.setdefault("properties", {})
            else:
                input_schema = {"type": "object", "properties": {}}

            async def _wrapper(_device_id=device_id, _tool_name=name, **kwargs):
                return await self.call_tool(_device_id, _tool_name, kwargs)

            device_map[name] = FunctionItem(
                name=name,
                description=description,
                func=_wrapper,
                type=ToolType.MCP_CLIENT,
                parameters=input_schema,
            )

        self._device_tools[device_id] = device_map
        logger.info(f"📡 DeviceMCP: đăng ký {len(device_map)} tool từ {device_id}")

    def unregister_device_tools(self, device_id: str):
        """Gỡ tool của thiết bị khỏi cache per-device."""
        removed = self._device_tools.pop(device_id, {})
        if removed:
            logger.info(f"📡 DeviceMCP: gỡ {len(removed)} tool của {device_id}")

    def handle_mcp_message(self, device_id: str, payload: dict):
        """Xử lý message MCP nhận từ ESP32 (reply cho tools/call)."""
        msg_id = payload.get("id")
        if msg_id is None:
            return
        futs = self._pending_futures.get(device_id, {})
        fut = futs.pop(msg_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    async def _notify(
        self, device_id: str, method: str, params: dict | None = None
    ) -> None:
        transport = self._get_transport(device_id)
        if transport is None:
            return
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await transport.send_json({"type": "mcp", "payload": payload})

    async def _request(
        self,
        device_id: str,
        method: str,
        params: dict | None = None,
        timeout: float = 5.0,
    ) -> dict:
        transport = self._get_transport(device_id)
        if transport is None:
            raise RuntimeError(f"Thiết bị {device_id} chưa kết nối.")

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
                    "method": method,
                    "params": params or {},
                },
            })
            response = await asyncio.wait_for(fut, timeout=timeout)
            if response.get("error") is not None:
                raise RuntimeError(str(response["error"]))
            return response
        finally:
            self._pending_futures.get(device_id, {}).pop(req_id, None)

    async def discover_tools(self, device_id: str) -> None:
        """Negotiate MCP and cache all device tools, including paginated lists."""
        try:
            await self._request(
                device_id,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "xiaozhi-server", "version": "2.0.0"},
                },
            )
            await self._notify(device_id, "notifications/initialized")
            cursor = None
            tools = []
            while True:
                params = {} if cursor is None else {"cursor": cursor}
                response = await self._request(device_id, "tools/list", params)
                result = response.get("result") or {}
                tools.extend(result.get("tools") or [])
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            await self.register_device_tools(device_id, tools)
            logger.info(
                f"📡 DeviceMCP: discovery hoàn tất {len(tools)} tool từ {device_id}"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"📡 DeviceMCP: discovery lỗi {device_id}: {exc}")

    async def call_tool(
        self,
        device_id: str,
        tool_name: str,
        arguments: dict,
        timeout: float = 10.0,
    ) -> ActionResponse:
        """Gửi `tools/call` xuống ESP32 qua WS duy nhất và chờ reply."""
        transport = self._get_transport(device_id)
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
            if reply.get("error") is not None:
                err = reply["error"]
                err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                return ActionResponse(Action.ERROR, result=f"Lỗi thiết bị: {err_msg}")

            result = reply.get("result")
            if isinstance(result, dict) and result.get("isError") is True:
                parsed_error = _extract_mcp_result_payload(reply)
                return ActionResponse(
                    Action.ERROR,
                    result=f"Lỗi thiết bị: {parsed_error}",
                    data=parsed_error,
                )

            parsed = _extract_mcp_result_payload(reply)
            out = (
                json.dumps(parsed, ensure_ascii=False)
                if isinstance(parsed, (dict, list))
                else str(parsed)
            )
            return ActionResponse(Action.REQLLM, result=out)
        except asyncio.TimeoutError:
            return ActionResponse(
                Action.ERROR,
                result=f"Thiết bị {device_id} không phản hồi sau {timeout}s.",
            )
        except Exception as e:
            return ActionResponse(Action.ERROR, result=f"Lỗi gửi MCP: {e}")
        finally:
            self._pending_futures.get(device_id, {}).pop(req_id, None)


_manager: Optional[DeviceMCPManager] = None


def get_device_mcp_manager() -> DeviceMCPManager:
    global _manager
    if _manager is None:
        _manager = DeviceMCPManager()
    return _manager

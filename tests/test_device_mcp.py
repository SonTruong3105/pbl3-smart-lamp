"""Tests cho triết lý Device-Centric MCP: handshake, per-device isolation, routing."""
import asyncio
from types import SimpleNamespace

from app.core.device_hub import DeviceHub
from app.core.providers.tools.device_mcp_manager import DeviceMCPManager, get_device_mcp_manager
from app.core.providers.tools.unified.register import Action, all_function_registry
from app.core.providers.tools.unified.unified_tool_handler import UnifiedToolHandler
from app.core.routing.intent_filter import build_tool_schema, _select_relevant_device_tools


class _FakeTransport:
    def __init__(self, device_id: str, manager: DeviceMCPManager, pages: list[list[dict]]):
        self.device_id = device_id
        self.manager = manager
        self.pages = pages
        self.sent: list[dict] = []
        self.is_connected = True

    async def send_json(self, msg: dict):
        self.sent.append(msg)
        payload = msg.get("payload", {})
        method = payload.get("method")
        req_id = payload.get("id")
        if method == "initialize":
            self.manager.handle_mcp_message(self.device_id, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
            })
        elif method == "tools/list":
            cursor = (payload.get("params") or {}).get("cursor")
            idx = 0 if cursor is None else int(cursor)
            tools = self.pages[idx]
            next_cursor = str(idx + 1) if idx + 1 < len(self.pages) else None
            result = {"tools": tools}
            if next_cursor is not None:
                result["nextCursor"] = next_cursor
            self.manager.handle_mcp_message(self.device_id, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            })
        elif method == "tools/call":
            params = payload.get("params") or {}
            self.manager.handle_mcp_message(self.device_id, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f'{{"ok": true, "tool": "{params.get("name")}"}}'}]
                },
            })


def test_mcp_handshake_pagination_and_per_device_isolation():
    async def run():
        mgr = DeviceMCPManager()
        dev1 = "AA:BB:CC:11:22:33"
        dev2 = "DD:EE:FF:44:55:66"

        t1 = _FakeTransport(dev1, mgr, pages=[
            [{"name": "self.audio_speaker.set_volume", "description": "Set volume", "inputSchema": {"type": "object", "properties": {"volume": {"type": "integer"}}}}],
            [{"name": "self.chassis.move", "description": "Move robot", "inputSchema": {"type": "object", "properties": {"dir": {"type": "string"}}}}],
        ])
        t2 = _FakeTransport(dev2, mgr, pages=[
            [{"name": "self.light.turn_on", "description": "Turn on light", "inputSchema": {"type": "object", "properties": {}}}],
        ])

        mgr.attach(dev1, t1)
        mgr.attach(dev2, t2)
        await mgr.discover_tools(dev1)
        await mgr.discover_tools(dev2)

        # 1. Verify handshake sequence: initialize -> notifications/initialized -> tools/list
        methods1 = [m["payload"]["method"] for m in t1.sent]
        assert methods1 == ["initialize", "notifications/initialized", "tools/list", "tools/list"]

        # 2. Verify tools are isolated per device & not leaked into global registry
        assert set(mgr.get_device_tools(dev1).keys()) == {
            "self.audio_speaker.set_volume",
            "self.chassis.move",
        }
        assert set(mgr.get_device_tools(dev2).keys()) == {"self.light.turn_on"}
        assert "self.chassis.move" not in all_function_registry
        assert not any(k.startswith("dev_") for k in all_function_registry)

        # 3. Detaching a transport preserves cached schemas for transient reconnects
        mgr.detach(dev1, transport=t1)
        assert set(mgr.get_device_tools(dev1).keys()) == {
            "self.audio_speaker.set_volume",
            "self.chassis.move",
        }
        assert set(mgr.get_device_tools(dev2).keys()) == {"self.light.turn_on"}

    asyncio.run(run())


def test_build_tool_schema_and_unified_execution_uses_device_tools():
    async def run():
        mgr = get_device_mcp_manager()
        dev = "11:22:33:44:55:66"
        t = _FakeTransport(dev, mgr, pages=[[
            {"name": "self.fan.set_speed", "description": "Set fan speed", "inputSchema": {"type": "object", "properties": {"speed": {"type": "integer"}}}},
        ]])
        mgr.attach(dev, t)
        try:
            await mgr.discover_tools(dev)

            schema = build_tool_schema("bật quạt số 2", device_id=dev)
            names = [s["function"]["name"] for s in schema]
            assert "self.fan.set_speed" in names
            assert "control_light" not in names

            handler = UnifiedToolHandler()
            conn = SimpleNamespace(device_id=dev, transport=t)
            resp = await handler.execute(conn, "self.fan.set_speed", {"speed": 2})
            assert resp.action == Action.REQLLM
            assert "self.fan.set_speed" in resp.result
        finally:
            mgr.detach(dev, transport=t)

    asyncio.run(run())


def test_small_model_device_tool_filter_prefers_matching_action_and_falls_back():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "Lamp.TurnOn",
                "description": "Turn the lamp on",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "Lamp.SetBrightness",
                "description": "Set lamp brightness",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "self.fan.turn_on",
                "description": "Turn the fan on",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "self.lights.set_warm_cool",
                "description": "Set warm and cool light brightness",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "self.lights.set_brightness_temp",
                "description": "Set overall brightness and color temperature",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    selected, narrowed = _select_relevant_device_tools(tools, "bật đèn")
    assert narrowed is True
    assert [t["function"]["name"] for t in selected] == ["Lamp.TurnOn"]

    selected, narrowed = _select_relevant_device_tools(tools, "chuyển đèn sang màu trung tính")
    assert narrowed is True
    assert [t["function"]["name"] for t in selected] == ["self.lights.set_warm_cool"]

    selected, narrowed = _select_relevant_device_tools(
        tools, "đặt độ sáng 65 phần trăm và màu trung tính",
    )
    assert narrowed is True
    assert [t["function"]["name"] for t in selected] == ["self.lights.set_brightness_temp"]

    selected, narrowed = _select_relevant_device_tools(tools, "bật thiết bị")
    assert narrowed is False
    assert selected == tools


def test_device_mcp_is_error_result_returns_action_error():
    async def run():
        mgr = DeviceMCPManager()
        dev = "AA:AA:AA:AA:AA:AA"

        class ErrorTransport:
            is_connected = True

            async def send_json(self, msg):
                payload = msg["payload"]
                mgr.handle_mcp_message(dev, {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": "Lamp failed"}],
                    },
                })

        transport = ErrorTransport()
        mgr.attach(dev, transport)
        response = await mgr.call_tool(dev, "Lamp.TurnOff", {})
        assert response.action == Action.ERROR
        assert "Lỗi thiết bị" in response.result

    asyncio.run(run())


def test_device_hub_online_ids_uses_mcp_manager():
    mgr = get_device_mcp_manager()
    dev = "99:88:77:66:55:44"
    t = _FakeTransport(dev, mgr, pages=[[]])
    mgr.attach(dev, t)
    try:
        hub = DeviceHub()
        assert dev in hub.online_devices()
        assert hub.is_online(dev) is True
    finally:
        mgr.detach(dev, transport=t)

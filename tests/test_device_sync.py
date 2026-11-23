"""Contract test cho UI dashboard sync (/ws/sync) và device targeting."""
import json

from app.core import device_sync_hub, lamp_state
from app.core.connection import ConnectionHandler
from app.core.providers.tools import sensor_state
from app.core.providers.tools import builtin
from app.routes import device_sync_ws


def test_normalize_sensor_payload_light_lux_alias():
    out = device_sync_ws.normalize_sensor_payload(
        {"device_id": "AA:BB", "temperature": 27.5, "light_lux": 120}
    )
    assert out == {"temperature": 27.5, "light_lux": 120, "lux": 120}
    assert "device_id" not in out


def test_normalize_sensor_payload_keeps_existing_lux():
    out = device_sync_ws.normalize_sensor_payload({"lux": 99, "light_lux": 120})
    assert out["lux"] == 99


def test_parse_mcp_result_from_json_rpc_text():
    reply = {"content": [{"type": "text", "text": json.dumps({"temperature": 27.5, "lux": 120})}]}
    assert device_sync_hub.parse_mcp_result({"ok": True, "reply": reply}) == {
        "temperature": 27.5, "lux": 120
    }


def test_parse_mcp_result_direct_dict():
    assert device_sync_hub.parse_mcp_result(
        {"ok": True, "reply": {"on": True, "brightness": 80}}
    ) == {"on": True, "brightness": 80}


def test_parse_mcp_result_error_is_none():
    assert device_sync_hub.parse_mcp_result({"ok": False, "error": "offline"}) is None


def test_lamp_state_update():
    lamp_state.update({"on": True, "brightness": 80, "cct": 50, "kelvin": 4500, "junk": 1})
    state = lamp_state.get_all()
    assert state["on"] is True
    assert state["brightness"] == 80
    assert "junk" not in state


def test_lamp_state_isolated_by_device():
    lamp_state.update({"on": True, "brightness": 80}, device_id="LAMP-A")
    lamp_state.update({"on": False, "brightness": 15}, device_id="LAMP-B")
    assert lamp_state.get_all("LAMP-A")["brightness"] == 80
    assert lamp_state.get_all("LAMP-B")["brightness"] == 15


def test_sensor_state_isolated_by_device():
    sensor_state.update_bulk({"temperature": 22.5}, device_id="LAMP-A")
    sensor_state.update_bulk({"temperature": 29.0}, device_id="LAMP-B")
    assert sensor_state.get_all("LAMP-A")["temperature"] == 22.5
    assert sensor_state.get_all("LAMP-B")["temperature"] == 29.0


def test_sensor_state_lux_alias():
    sensor_state.update_bulk({"temperature": 27.5, "lux": 120})
    state = sensor_state.get_all()
    assert state["lux"] == 120
    assert state["light_lux"] == 120


def test_connection_handler_transport_alias():
    # Không gọi __init__ vì có _init_providers() nặng — chỉ kiểm tra alias.
    handler = object.__new__(ConnectionHandler)
    handler.ws = object()
    assert handler.transport is handler.ws
    assert hasattr(handler.transport, "__class__")


def test_routes_registered():
    paths = [getattr(r, "path", None) for r in device_sync_ws.router.routes]
    assert "/ws/sync/{device_id}" in paths
    assert "/api/devices/{device_id}/command" in paths


def test_active_devices_control_includes_mqtt_and_hub(monkeypatch):
    from app.routes import observe

    class _Hub:
        def get_active_devices(self):
            return {"HUB-DEVICE"}

    monkeypatch.setattr(observe, "get_hub", lambda: _Hub())
    monkeypatch.setattr(observe, "online_devices", lambda: {"MQTT-DEVICE"})
    result = __import__("asyncio").run(observe.active_devices())
    assert result == {"devices": ["HUB-DEVICE", "MQTT-DEVICE"]}


def test_active_devices_chat_uses_audio_registry(monkeypatch):
    from app.routes import observe
    from app.core import sync

    monkeypatch.setattr(sync, "all_esp32", lambda: ["CHAT-DEVICE"])
    result = __import__("asyncio").run(observe.active_devices(capability="chat"))
    assert result == {"devices": ["CHAT-DEVICE"]}


def test_dashboard_command_success_and_error(monkeypatch):
    async def fake_send(tool, args, timeout, device_id):
        if device_id == "GOOD":
            return {"ok": True, "reply": {"on": True, "brightness": 77}}
        return {"ok": False, "error": "offline"}

    monkeypatch.setattr(builtin, "_send_mcp_command", fake_send)
    import asyncio
    success = asyncio.run(device_sync_ws._execute_command("GOOD", "Lamp.GetState", {}))
    failure = asyncio.run(device_sync_ws._execute_command("OFFLINE", "Lamp.TurnOn", {}))
    assert success["ok"] is True and success["result"]["on"] is True
    assert failure["ok"] is False and failure["error"] == "offline"


def test_dashboard_command_rejects_unlisted_tool(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("MCP should not be invoked")

    monkeypatch.setattr(builtin, "_send_mcp_command", fail_if_called)
    result = __import__("asyncio").run(device_sync_ws._execute_command("DEVICE", "system.exec", {}))
    assert not result["ok"]
    assert "không được phép" in result["error"]


def test_legacy_lamp_state_is_not_assigned_to_device(monkeypatch, tmp_path):
    monkeypatch.setattr(lamp_state, "_STATE_FILE", tmp_path / "lamp.json")
    lamp_state._devices.clear()
    lamp_state._state = dict(lamp_state._FIELDS)
    lamp_state._STATE_FILE.write_text('{"on": true, "brightness": 63}', encoding="utf-8")
    lamp_state._load()
    assert lamp_state.get_all()["brightness"] == 63
    assert lamp_state.get_all("UNRELATED-DEVICE")["brightness"] is None


def test_legacy_sensor_state_is_not_assigned_to_device(monkeypatch, tmp_path):
    monkeypatch.setattr(sensor_state, "_STATE_FILE", tmp_path / "sensor.json")
    sensor_state._devices.clear()
    sensor_state._state = dict(sensor_state._FIELDS)
    sensor_state._STATE_FILE.write_text('{"temperature": 24.5, "lux": 85}', encoding="utf-8")
    sensor_state._load()
    assert sensor_state.get_all()["temperature"] == 24.5
    assert sensor_state.get_all("UNRELATED-DEVICE")["temperature"] is None


class _FakeAction:
    ERROR = "error"
    REQLLM = "reqllm"


class _FakeDeviceManager:
    def __init__(self):
        self._transports = {"WS-DEVICE": object()}
        self._control_transports = {}
        self.calls = []

    def has_control_channel(self, device_id):
        return device_id in self._control_transports

    async def call_tool(self, device_id, method, params, timeout):
        self.calls.append((device_id, method, params, timeout))
        return type("A", (), {"action": "ok", "result": {"reply": "done"}})()


class _FakeMQTT:
    def __init__(self):
        self.sessions = {"MQTT-DEVICE": {}}


def test_send_mcp_command_routes_to_explicit_ws_device(monkeypatch):
    dm = _FakeDeviceManager()
    mqtt = _FakeMQTT()
    monkeypatch.setattr(
        "app.core.providers.tools.device_mcp_manager.get_device_mcp_manager", lambda: dm
    )
    monkeypatch.setattr("app.core.mqtt_server.get_mqtt_manager", lambda: mqtt)

    import asyncio
    result = asyncio.run(builtin._send_mcp_command("Lamp.GetState", {}, 1.0, "WS-DEVICE"))

    assert result["ok"] is True
    assert result["device_id"] == "WS-DEVICE"
    assert dm.calls[0][0] == "WS-DEVICE"
    assert dm.calls[0][1] == "Lamp.GetState"


def test_send_mcp_command_unknown_device_does_not_fall_back(monkeypatch):
    dm = _FakeDeviceManager()
    mqtt = _FakeMQTT()
    monkeypatch.setattr(
        "app.core.providers.tools.device_mcp_manager.get_device_mcp_manager", lambda: dm
    )
    monkeypatch.setattr("app.core.mqtt_server.get_mqtt_manager", lambda: mqtt)

    import asyncio
    result = asyncio.run(builtin._send_mcp_command("Lamp.GetState", {}, 1.0, "NOPE"))

    assert result["ok"] is False
    assert "NOPE" in result["error"]
    assert not dm.calls

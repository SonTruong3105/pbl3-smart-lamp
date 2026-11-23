"""Quick test script for DeviceHub, PM2.5 sensor state, lamp sync, and WS/HTTP routes."""
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.device_hub import SENSOR_KEYS, get_device_hub, parse_mcp_result
from app.routes.device_sync_ws import router as sync_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(sync_router)
    return app


def test_hub_state_and_pm25():
    hub = get_device_hub()
    device_id = "AA:BB:CC:DD:EE:01"

    assert "pm25" in SENSOR_KEYS
    assert "air_quality_ppm" not in SENSOR_KEYS

    hub.update_lamp({"on": True, "brightness": 75, "cct": 40}, device_id=device_id)
    lamp = hub.get_lamp(device_id=device_id)
    assert lamp["on"] is True
    assert lamp["brightness"] == 75
    assert lamp["cct"] == 40

    # Chỉ các key thuộc SENSOR_KEYS mới được giữ lại
    hub.update_sensors(
        {"temperature": 28.5, "humidity": 65, "pm25": 18.4, "air_quality_ppm": 999},
        device_id=device_id,
    )
    sensors = hub.get_all_sensors(device_id=device_id)
    assert sensors["temperature"] == 28.5
    assert sensors["humidity"] == 65
    assert sensors["pm25"] == 18.4
    assert "air_quality_ppm" not in sensors
    assert hub.is_sensor_fresh(max_age_sec=60, device_id=device_id) is True


def test_parse_mcp_result():
    raw = {
        "ok": True,
        "reply": {
            "content": [
                {"type": "text", "text": '{"temperature": 29.1, "pm25": 62.0}'}
            ]
        },
    }
    parsed = parse_mcp_result(raw)
    assert parsed == {"temperature": 29.1, "pm25": 62.0}


def test_http_and_ws_sync_endpoints():
    hub = get_device_hub()
    device_id = "AA:BB:CC:DD:EE:02"
    app = _build_app()
    client = TestClient(app)

    # 1. Test POST /api/sensor/report với PM2.5
    resp = client.post(
        "/api/sensor/report",
        headers={"Device-Id": device_id},
        json={"temperature": 27.0, "humidity": 60, "pm25": 22.5},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert hub.get_sensor("pm25", device_id=device_id) == 22.5

    # 2. Test POST /api/devices/{device_id}/command (mock _send_mcp_command)
    fake_mcp = AsyncMock(
        return_value={
            "ok": True,
            "reply": {"content": [{"type": "text", "text": '{"on": true, "brightness": 85}'}]},
        }
    )
    with patch("app.core.providers.tools.builtin._send_mcp_command", fake_mcp):
        cmd_resp = client.post(
            f"/api/devices/{device_id}/command",
            json={"tool": "Lamp.SetBrightness", "args": {"value": 85}},
        )
        assert cmd_resp.status_code == 200
        assert cmd_resp.json()["ok"] is True
        assert hub.get_lamp(device_id=device_id)["brightness"] == 85

    # 3. Test /ws/sync/{device_id} nhận full_state ban đầu
    with client.websocket_connect(f"/ws/sync/{device_id}") as ws:
        init_msg = ws.receive_json()
        assert init_msg["type"] == "full_state"
        assert init_msg["data"]["sensors"]["pm25"] == 22.5
        assert init_msg["data"]["lamp"]["brightness"] == 85

    # 4. Test trạng thái online/offline qua register_esp32 / unregister_esp32
    dummy_handler = object()
    assert hub.is_online(device_id) is False
    hub.register_esp32(device_id, dummy_handler)
    assert hub.is_online(device_id) is True
    hub.unregister_esp32(device_id, dummy_handler)
    assert hub.is_online(device_id) is False


if __name__ == "__main__":
    test_hub_state_and_pm25()
    test_parse_mcp_result()
    test_http_and_ws_sync_endpoints()
    asyncio.run(asyncio.sleep(0))
    print("ALL QUICK TESTS PASSED")
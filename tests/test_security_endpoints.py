import asyncio
from types import SimpleNamespace

from app.core import broadcast_hub
from app.core.api import ota_handler
from app.routes import observe, web


def test_ota_never_returns_device_token(monkeypatch):
    monkeypatch.setattr(ota_handler.config, "auth_enabled", True)
    monkeypatch.setattr(ota_handler.config, "mqtt_enabled", False)
    request = SimpleNamespace(
        headers={"Device-Id": "device-1", "host": "example.test"}
    )

    response = ota_handler._build_ota_response(request, {})

    assert response["websocket"]["token"] == ""


def test_log_route_rejects_path_components(monkeypatch):
    def should_not_read(*args, **kwargs):
        raise AssertionError("filesystem lookup should not happen")

    monkeypatch.setattr(web, "read_session_log", should_not_read)

    response = asyncio.run(web.api_log_content("../secret"))

    assert "error" in response


def test_broadcast_hub_discards_raw_audio():
    hub = broadcast_hub.BroadcastHub()

    asyncio.run(hub.broadcast("device-1", {"type": "user_wav", "data": "private"}))

    assert hub.get_history("device-1") == []


def test_observe_requires_device_token(monkeypatch):
    monkeypatch.setattr(observe.config, "auth_enabled", True)
    monkeypatch.setattr(observe, "verify_device_token", lambda device_id, token: False)

    class FakeWebSocket:
        query_params = {"device_id": "device-1"}
        headers = {}
        closed = None
        accepted = False

        async def close(self, **kwargs):
            self.closed = kwargs

        async def accept(self):
            self.accepted = True

    ws = FakeWebSocket()
    asyncio.run(observe.observe_ws(ws))

    assert ws.closed["code"] == 4403
    assert not ws.accepted

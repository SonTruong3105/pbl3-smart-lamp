"""Observe route — mirror ESP32 realtime cho web."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.config import config
from app.core.device_auth import verify_device_token
from app.core.device_hub import get_device_hub

router = APIRouter()


@router.get("/api/devices/active")
async def active_devices(capability: str = "control"):
    """List active ESP32 devices; chat capability requires an audio handler."""
    hub = get_device_hub()
    if capability == "chat":
        devices = set(hub.all_esp32())
    else:
        devices = set(hub.get_active_devices()) | hub.online_devices()
    return {"devices": sorted(devices)}


@router.websocket("/ws/observe")
async def observe_ws(ws: WebSocket):
    device_id = ws.query_params.get("device_id", "").strip()
    if not device_id or len(device_id) > 128:
        await ws.close(code=4400, reason="Invalid device_id")
        return
    if not config.auth_enabled:
        await ws.close(code=4403, reason="Device authentication is disabled")
        return
    auth_header = ws.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
    if not verify_device_token(device_id, token):
        await ws.close(code=4403, reason="Unauthorized")
        return
    await ws.accept()

    hub = get_device_hub()
    await hub.subscribe_events(device_id, ws)

    # Gửi lịch sử (up to 100 events)
    try:
        for event in hub.get_event_history(device_id):
            await ws.send_json(event)
    except Exception as e:
        logger.debug(f"observe history send fail: {e}")

    try:
        while True:
            try:
                data = await ws.receive_text()
            except WebSocketDisconnect:
                break
            if data == "ping":
                try:
                    await ws.send_json({"type": "pong"})
                except Exception:
                    break
    except Exception as e:
        logger.debug(f"observe ws error: {e}")
    finally:
        await hub.unsubscribe_events(device_id, ws)
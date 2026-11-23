"""UI dashboard đèn — /ws/sync/{device_id} + POST /api/devices/{device_id}/command.

Bổ sung cho chat.js/lamp_sync.js (endpoint này trước đây bị thiếu).
Mọi lệnh đều đi qua MCP xuống đúng device_id, UI chỉ cập nhật sau khi có result.
"""
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.core.device_hub import SENSOR_KEYS, get_device_hub, parse_mcp_result

router = APIRouter()

_DASHBOARD_TOOLS = {
    "Lamp.GetState", "Lamp.TurnOn", "Lamp.TurnOff",
    "Lamp.SetBrightness", "Lamp.SetColorTemp", "self.get_environment",
}


def normalize_sensor_payload(body: dict) -> dict:
    """Chuẩn hóa payload sensor từ firmware (đổi light_lux -> lux)."""
    data = dict(body)
    data.pop("device_id", None)
    data.pop("session_id", None)
    if "light_lux" in data and "lux" not in data:
        data["lux"] = data["light_lux"]
    return data


async def _push_sensor_to_web(device_id: str, data: dict) -> int:
    """Đẩy sensor_update tới mọi UI đang theo dõi device (không cần ESP32 nói)."""
    hub = get_device_hub()
    sent = 0

    # 1. UI /ws/sync/{device_id}
    sent += await hub.broadcast_sync(device_id, "sensor_update", data)

    # 2. Web chat /ws/chat đã link tới device này
    msg = {
        "type": "sensor_update",
        "esp32_device_id": device_id,
        "data": data,
        **data,
    }
    for _web_id, chat_ws in hub.get_chats_by_device(device_id):
        try:
            await chat_ws.send_json(msg)
            sent += 1
        except Exception:
            pass

    # 3. Observer /ws/observe
    try:
        await hub.broadcast_event(device_id, {
            "type": "sensor_update", "data": data, **data,
        })
    except Exception:
        pass
    return sent


@router.post("/api/sensor/report")
async def sensor_report(request: Request):
    """ESP32 push cảm biến qua HTTP bất kỳ lúc nào (kể cả idle, không nói).

    Không cần mở audio channel / WS session — chỉ cần device đã có WiFi.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "expected object"}, status_code=400)

    header_device_id = (request.headers.get("Device-Id") or "").strip()
    body_device_id = (body.get("device_id") or "").strip()
    device_id = header_device_id or body_device_id
    if not device_id:
        return JSONResponse({"ok": False, "error": "missing device id"}, status_code=400)

    if config.auth_enabled:
        from app.core.device_auth import verify_device_token
        auth_header = request.headers.get("Authorization", "")
        token = request.headers.get("Device-Token", "")
        if not token:
            token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
        if not verify_device_token(device_id, token):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    if header_device_id and body_device_id and header_device_id != body_device_id:
        return JSONResponse({"ok": False, "error": "device id mismatch"}, status_code=400)

    data = normalize_sensor_payload(body)
    if not any(k in data for k in SENSOR_KEYS):
        return JSONResponse({"ok": False, "error": "no sensor fields"}, status_code=400)

    get_device_hub().update_sensors(data, device_id=device_id)
    sent = await _push_sensor_to_web(device_id, data)
    return {"ok": True, "device_id": device_id, "ui_clients": sent}


async def _execute_command(device_id: str, tool: str, args: dict) -> dict:
    """Gọi MCP tới đúng thiết bị rồi phát event cho UI sau khi có result."""
    from app.core.providers.tools.builtin import _send_mcp_command

    tool = (tool or "").strip()
    if not tool:
        return {"ok": False, "error": "Thiếu tên tool"}
    if tool not in _DASHBOARD_TOOLS:
        return {"ok": False, "tool": tool, "device_id": device_id, "error": "Tool không được phép từ dashboard."}

    try:
        result = await _send_mcp_command(
            tool, args if isinstance(args, dict) else {}, timeout=5.0, device_id=device_id
        )
    except Exception as exc:
        return {
            "ok": False,
            "tool": tool,
            "device_id": device_id,
            "result": None,
            "error": str(exc) or "Thiết bị không thực hiện được lệnh.",
        }
    if not isinstance(result, dict) or not result.get("ok"):
        error = result.get("error") if isinstance(result, dict) else None
        return {
            "ok": False,
            "tool": tool,
            "device_id": device_id,
            "result": None,
            "error": error or "Thiết bị không thực hiện được lệnh.",
        }

    hub = get_device_hub()
    data = parse_mcp_result(result)

    if data:
        if tool.startswith("Lamp."):
            hub.update_lamp(data, device_id=device_id)
            await hub.broadcast_sync(device_id, "lamp_update", data)
        elif any(key in data for key in SENSOR_KEYS):
            hub.update_sensors(data, device_id=device_id)
            await hub.broadcast_sync(device_id, "sensor_update", data)

    return {
        "ok": bool(result.get("ok")),
        "tool": tool,
        "device_id": device_id,
        "result": data,
        "error": result.get("error"),
    }


async def _refresh_state(device_id: str) -> None:
    """Xin lại state đèn + cảm biến ngay sau khi UI kết nối."""
    for tool in ("Lamp.GetState", "self.get_environment"):
        try:
            await _execute_command(device_id, tool, {})
        except Exception:
            pass


@router.websocket("/ws/sync/{device_id}")
async def device_sync_ws(ws: WebSocket, device_id: str):
    if not device_id or len(device_id) > 128:
        await ws.close(code=4400, reason="Invalid device_id")
        return
    await ws.accept()
    hub = get_device_hub()
    await hub.subscribe_sync(device_id, ws)
    try:
        await ws.send_json({
            "type": "full_state",
            "data": {
                "online": hub.is_online(device_id),
                "lamp": hub.get_lamp(device_id=device_id),
                "sensors": hub.get_all_sensors(device_id=device_id),
            },
        })
        asyncio.create_task(_refresh_state(device_id))

        while True:
            message = await ws.receive_json()
            if message.get("type") == "command":
                request_id = message.get("request_id")
                result = await _execute_command(
                    device_id, message.get("tool", ""), message.get("args") or {}
                )
                await ws.send_json({
                    "type": "command_result",
                    "request_id": request_id,
                    **result,
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.unsubscribe_sync(device_id, ws)
        # Closing a dashboard tab is not the same as the ESP32 going offline.
        if not hub.is_online(device_id):
            await hub.broadcast_sync(device_id, "device_status", {"online": False})


@router.post("/api/devices/{device_id}/command")
async def device_command(device_id: str, request: Request):
    """Fallback REST cho lamp_sync.js khi WS chưa sẵn sàng."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    return JSONResponse(await _execute_command(
        device_id, body.get("tool", ""), body.get("args") or {}
    ))
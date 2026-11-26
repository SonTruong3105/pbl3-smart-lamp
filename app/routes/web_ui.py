"""Web UI routes — HTML pages, logs, observe."""

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from app.config import config
from app.core.device_auth import verify_device_token
from app.core.device_hub import get_device_hub
from app.core.logger import list_session_logs, read_session_log

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ═══ WEB UI ═══
@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/index", response_class=HTMLResponse)
async def index_alias(request: Request):
    return await index_page(request)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return await index_page(request)


@router.get("/api/logs")
async def api_logs():
    return {"logs": list_session_logs()}


@router.get("/api/logs/{session_id}")
async def api_log_content(session_id: str, tail: int = 500):
    if not session_id.isascii() or not session_id.isdecimal():
        return {"error": "Không tìm thấy log"}
    tail = max(1, min(tail, 2000))
    content = read_session_log(session_id, tail=tail)
    if not content:
        return {"error": "Không tìm thấy log"}
    return {"content": content}


# ═══ OBSERVE ═══
@router.get("/api/devices/active")
async def active_devices(capability: str = "control"):
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

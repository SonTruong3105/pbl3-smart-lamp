import os
"""
OTA endpoint — cung cấp config cho firmware Xiaozhi ESP32.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import config


router = APIRouter()


def _get_ws_url(request: Request) -> str:
    """Sinh ws_url tu tunnel URL neu co, fallback ve Host header."""
    # Uu tien tunnel URL
    tunnel_url = os.environ.get("PUBLIC_WS_URL")
    if tunnel_url:
        # https://xxx.trycloudflare.com -> wss://xxx.trycloudflare.com/xiaozhi/v1/
        ws_url = tunnel_url.replace("https://", "wss://").replace("http://", "ws://")
        if not ws_url.endswith("/"):
            ws_url += "/"
        ws_url += "xiaozhi/v1/"
        logger.info(f"Dung tunnel URL cho WS: {ws_url}")
        return ws_url

    # Fallback: Host header
    host = request.headers.get("host", "192.168.1.19:8000")
    if ":" not in host:
        host = f"{host}:{config.port}"
    return f"ws://{host}/xiaozhi/v1/"
def _build_ota_response(request: Request, body: dict) -> dict:
    ws_url = _get_ws_url(request)

    # ⭐ FIX: Đọc MAC từ HEADER trước (firmware gửi ở đây), fallback body
    mac = (
        request.headers.get("Device-Id")
        or request.headers.get("device-id")
        or body.get("mac_address")
        or "esp32-unknown"
    )

    logger.info(
        f"📦 OTA request | host={request.headers.get('host')} "
        f"| mac={mac} "
        f"| version={body.get('application', {}).get('version', '?')}"
    )

    response = {
        "firmware": {
            "version": config.version,
            "url": "",
        },
        "transport": "udp",
        "websocket": {"url": ws_url, "token": ""},
        "server": {"websocket": {"url": ws_url, "token": ""}},
        "audio_params": {
            "format": "opus",
            "sample_rate": 24000,
            "channels": 1,
            "frame_duration": 60,
        },
        "server_time": {
            "timestamp": int(datetime.now().timestamp() * 1000),
            "timezone_offset": 7 * 60,
        },
    }

    if config.mqtt_enabled:
        mqtt_endpoint_with_port = f"{config.mqtt_endpoint}:{config.mqtt_broker_port}"
        response["mqtt"] = {
            "enable": True,
            "endpoint": mqtt_endpoint_with_port,
            "client_id": mac,                    # ⭐ Giờ là MAC đúng
            "username": mac,
            "password": "",
            "publish_topic": f"xiaozhi/{mac}/up",  # ⭐ Topic đúng
        }
        # ⭐ THÊM: UDP info (firmware cần biết để gửi audio)
        response["udp"] = {
            "server": config.udp_endpoint,
            "port": config.udp_port,
        }
        logger.info(f"   → MQTT: {mqtt_endpoint_with_port}")
        logger.info(f"   → client_id: {mac}")
        logger.info(f"   → publish_topic: xiaozhi/{mac}/up")
        logger.info(f"   → UDP: {config.udp_endpoint}:{config.udp_port}")
    else:
        logger.info(f"   → WS: {ws_url}")

    return response

@router.post("/xiaozhi/ota")
@router.post("/xiaozhi/ota/")
async def ota_check(request: Request):
    """Endpoint OTA — firmware gọi đầu tiên khi boot."""
    try:
        raw = await request.body()
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {}

    response = _build_ota_response(request, body)
    return JSONResponse(content=response)


@router.get("/xiaozhi/ota")
@router.get("/xiaozhi/ota/")
async def ota_check_get(request: Request):
    """Firmware cũ có thể dùng GET — hỗ trợ cả 2."""
    response = _build_ota_response(request, {})
    return JSONResponse(content=response)
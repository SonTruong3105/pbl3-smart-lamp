import os
"""
OTA endpoint — cung cấp config cho firmware Xiaozhi ESP32.
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
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


def _get_firmware_info(request: Request) -> tuple[str, str, int]:
    """Lấy firmware version, URL, force từ config.

    Returns:
        (version, url, force)
    """
    fw_version = config._get("firmware", "version", default="1.0.0")
    fw_url = config._get("firmware", "url", default="")
    fw_force = int(config._get("firmware", "force", default=0))

    # Nếu không có URL, tự sinh từ thư mục static/firmware
    if not fw_url:
        fw_dir = Path(config._get("firmware", "dir", default="static/firmware"))
        if fw_dir.exists():
            fw_files = sorted(
                fw_dir.glob("*.bin"),
                key=os.path.getmtime,
                reverse=True,
            )
            if fw_files:
                # Sinh URL từ request host (hỗ trợ cả HTTP và HTTPS)
                base = str(request.base_url).rstrip("/")
                fw_url = f"{base}/static/firmware/{fw_files[0].name}"
                logger.info(f"OTA firmware URL (auto): {fw_url}")

    return fw_version, fw_url, fw_force


def _build_ota_response(request: Request, body: dict) -> dict:
    ws_url = _get_ws_url(request)

    # ⭐ FIX: Đọc MAC từ HEADER trước (firmware gửi ở đây), fallback body
    mac = (
        request.headers.get("Device-Id")
        or request.headers.get("device-id")
        or body.get("mac_address")
        or "esp32-unknown"
    )

    # Firmware sends Device-Id on initial OTA but has no credential yet. A
    # self-asserted MAC is not proof of device identity, so never provision or
    # disclose a registered token through this public bootstrap endpoint.
    if config.auth_enabled:
        logger.warning(f"OTA config requested while device auth is enabled: {mac}")

    # ⭐ Lấy firmware info từ config
    fw_version, fw_url, fw_force = _get_firmware_info(request)
    current_version = body.get("application", {}).get("version", "?")

    logger.info(
        f"📦 OTA request | host={request.headers.get('host')} "
        f"| mac={mac} "
        f"| current_version={current_version} "
        f"| server_version={fw_version}"
    )

    response = {
        "firmware": {
            "version": fw_version,   # ✅ Version firmware (từ config)
            "url": fw_url,           # ✅ URL tải firmware
            "force": fw_force,       # ✅ Flag ép buộc
        },
        # ⭐ ĐÃ SỬA DÒNG NÀY: Tự động chọn websocket nếu mqtt tắt
        "transport": "udp" if config.mqtt_enabled else "websocket",
        "websocket": {"url": ws_url, "token": "", "version": 1},
        "audio_params": {
            "format": "opus",
            "sample_rate": config.sample_rate,
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
            "client_id": mac,
            "username": mac,
            "password": "",
            "publish_topic": f"xiaozhi/{mac}/up",
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

    # ⭐ Log firmware info
    if fw_url:
        logger.info(f"   → Firmware: v{fw_version} @ {fw_url}")
    else:
        logger.warning(f"   → Firmware: v{fw_version} @ (URL trống — chưa có file .bin)")

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
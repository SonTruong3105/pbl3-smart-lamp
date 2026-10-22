import os

# =====================================================
# 🚨 FIX LỖI TẠI ĐÂY (Phải đặt trước mọi import khác)
# =====================================================
# 1. Tắt symlink để ONNX Runtime không báo lỗi bảo mật
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
# 2. Ép Hugging Face và Transformers chạy Offline (chỉ dùng file trong ổ cứng)
# Giúp ASR và TTS load siêu nhanh, không bị treo do check mạng
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import tunnel_bootstrap  # Auto-start Cloudflare tunnel
"""Entry point — tự động khởi động Ollama, ASR, VieNeu-TTS rồi chạy FastAPI.

Tự động tắt reload khi MQTT enabled (reload phá event loop policy trên Windows).
"""
import asyncio
import sys

# ✅ Fix Windows asyncio — PHẢI chạy trước mọi import khác
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import subprocess
import time
from pathlib import Path

import httpx
import yaml
import uvicorn
from loguru import logger


# =====================================================
# CẤU HÌNH ĐƯỜNG DẪN
# =====================================================

ROOT_DIR = Path(__file__).parent

# ASR
ASR_DIR = ROOT_DIR / "asr"
ASR_SCRIPT = ASR_DIR / "phowhisper_server.py"
ASR_URL = "http://localhost:11435"

# VieNeu-TTS
VIENEU_DIR = ROOT_DIR / "vieneu-server"
VIENEU_SCRIPT = VIENEU_DIR / "server.py"
VIENEU_URL = "http://localhost:11436"

# Ollama
OLLAMA_URL = "http://localhost:11434"

# Mosquitto
MQTT_HOST = "localhost"
MQTT_PORT = 1883


def venv_python(venv: Path) -> Path:
    """Return the platform-specific Python executable in a virtualenv."""
    executable = "python.exe" if sys.platform == "win32" else "python"
    subdirectory = "Scripts" if sys.platform == "win32" else "bin"
    return venv / subdirectory / executable


PROJECT_PYTHON = venv_python(ROOT_DIR / "venv")
ASR_PYTHON = PROJECT_PYTHON


# =====================================================
# HÀM CHECK
# =====================================================

def is_ollama_running() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def is_asr_running() -> bool:
    try:
        r = httpx.get(f"{ASR_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def is_vieneu_running() -> bool:
    try:
        r = httpx.get(f"{VIENEU_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def is_mqtt_running() -> bool:
    """Check Mosquitto broker trên TCP 1883."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        result = s.connect_ex((MQTT_HOST, MQTT_PORT))
        s.close()
        return result == 0
    except Exception:
        return False


# =====================================================
# HÀM START
# =====================================================

def start_ollama() -> bool:
    if is_ollama_running():
        logger.success("✅ Ollama đã chạy")
        return True

    logger.info("🚀 Khởi động Ollama...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        logger.error(f"❌ Không chạy được Ollama: {e}")
        return False

    for i in range(15):
        time.sleep(1)
        if is_ollama_running():
            logger.success(f"✅ Ollama sẵn sàng sau {i + 1}s")
            return True
        print(f"   {i + 1}/15s...", end="\r")

    print()
    logger.warning("⚠️  Ollama chưa sẵn sàng, tiếp tục...")
    return False


def start_asr() -> bool:
    """Khởi động ASR server."""
    if is_asr_running():
        logger.success("✅ ASR server đã chạy")
        return True

    if not ASR_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy python ASR: {ASR_PYTHON}")
        logger.error("   Tạo venv ASR: cd asr && python -m venv venv")
        return False

    if not ASR_SCRIPT.exists():
        logger.error(f"❌ Không tìm thấy script: {ASR_SCRIPT}")
        return False

    logger.info("🚀 Khởi động ASR server...")
    try:
        command = [str(ASR_PYTHON), str(ASR_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "ASR Server"] + command
        # Truyền toàn bộ biến môi trường (bao gồm cả HF_HUB_OFFLINE) vào tiến trình con
        subprocess.Popen(command, cwd=str(ASR_DIR), env=os.environ.copy())
    except Exception as e:
        logger.error(f"❌ Không chạy được ASR: {e}")
        return False

    logger.info("⏳ Đợi ASR khởi động (lần đầu có thể lâu)...")
    for i in range(90):
        time.sleep(1)
        if is_asr_running():
            logger.success(f"✅ ASR sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 5 == 0:
            print(f"   {i + 1}/90s...", end="\r")

    print()
    logger.warning("⚠️  ASR chưa sẵn sàng sau 90s, tiếp tục...")
    return False


def start_vieneu() -> bool:
    """Khởi động VieNeu-TTS server."""
    if is_vieneu_running():
        logger.success("✅ VieNeu-TTS đã chạy")
        return True

    if not PROJECT_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy Python project: {PROJECT_PYTHON}")
        logger.error("   Tạo venv: python -m venv venv")
        return False

    if not VIENEU_SCRIPT.exists():
        logger.error(f"❌ Không tìm thấy script: {VIENEU_SCRIPT}")
        return False

    logger.info("🚀 Khởi động VieNeu-TTS server...")
    try:
        command = [str(PROJECT_PYTHON), str(VIENEU_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "VieNeu-TTS Server"] + command
        # Truyền toàn bộ biến môi trường (bao gồm cả HF_HUB_DISABLE_SYMLINKS) vào tiến trình con
        subprocess.Popen(command, cwd=str(VIENEU_DIR), env=os.environ.copy())
    except Exception as e:
        logger.error(f"❌ Không chạy được VieNeu-TTS: {e}")
        return False

    logger.info("⏳ Đợi VieNeu-TTS khởi động...")
    for i in range(120):
        time.sleep(1)
        if is_vieneu_running():
            logger.success(f"✅ VieNeu-TTS sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 5 == 0:
            print(f"   {i + 1}/120s...", end="\r")

    print()
    logger.warning("⚠️  VieNeu-TTS chưa sẵn sàng sau 120s, tiếp tục...")
    return False


def check_mqtt() -> bool:
    if is_mqtt_running():
        logger.success(f"✅ Mosquitto đang chạy ({MQTT_HOST}:{MQTT_PORT})")
        return True
    else:
        logger.warning(f"⚠️  Mosquitto chưa chạy ({MQTT_HOST}:{MQTT_PORT})")
        logger.warning("   Chạy: sudo systemctl start mosquitto")
        return False


def load_config() -> dict:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# =====================================================
# MAIN
# =====================================================

def main():
    print()
    logger.info("═" * 50)
    logger.info("  🚀 XIAOZHI SERVER - START")
    logger.info("═" * 50)

    cfg = load_config()
    mqtt_enabled = cfg.get("mqtt", {}).get("enabled", False)

    logger.info("\n[1/5] Ollama...")
    start_ollama()

    logger.info("\n[2/5] ASR server...")
    start_asr()

    logger.info("\n[3/5] VieNeu-TTS server...")
    start_vieneu()

    logger.info("\n[4/5] Mosquitto MQTT...")
    if mqtt_enabled:
        check_mqtt()
    else:
        logger.info("⏭️  MQTT disabled trong config.yaml")

    logger.info("\n[5/5] FastAPI server...")
    if mqtt_enabled:
        reload_mode = False
    else:
        reload_mode = True

    logger.info("")
    logger.info("═" * 50)
    logger.info(f"  🌐 http://localhost:8000/chat")
    logger.info(f"  🌐 http://localhost:8000/admin")
    logger.info(f"  🔧 Reload: {'OFF' if not reload_mode else 'ON'}")
    logger.info(f"  📡 MQTT:   {'ENABLED' if mqtt_enabled else 'disabled'}")
    logger.info("═" * 50)
    logger.info("")

    if reload_mode:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, loop="asyncio")
    else:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, loop="asyncio", access_log=False)


if __name__ == "__main__":
    main()
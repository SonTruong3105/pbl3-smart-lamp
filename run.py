import tunnel_bootstrap  # Auto-start Cloudflare tunnel
"""Entry point — tự động khởi động Ollama, SearXNG, ASR, VieNeu-TTS rồi chạy FastAPI.

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

# SearXNG
SEARXNG_DIR = ROOT_DIR / "SearXNGforWindows-main"
SEARXNG_VBS = SEARXNG_DIR / "SearXNG for Windows.vbs"
SEARXNG_URL = "http://localhost:8888"

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


def is_searxng_running() -> bool:
    try:
        r = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": "test", "format": "json"},
            timeout=3.0,
        )
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


def start_searxng() -> bool:
    if is_searxng_running():
        logger.success("✅ SearXNG đã chạy")
        return True

    if sys.platform != "win32":
        logger.info("⏭️  SearXNG launcher chỉ hỗ trợ Windows; dùng fallback ddgs")
        return False

    if not SEARXNG_VBS.exists():
        logger.error(f"❌ Không tìm thấy: {SEARXNG_VBS}")
        return False

    logger.info(f"🚀 Khởi động SearXNG từ {SEARXNG_VBS.name}")
    try:
        subprocess.Popen(
            ["wscript.exe", str(SEARXNG_VBS)],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        logger.error(f"❌ Không chạy được VBS: {e}")
        return False

    logger.info("⏳ Đợi SearXNG khởi động...")
    for i in range(30):
        time.sleep(1)
        if is_searxng_running():
            logger.success(f"✅ SearXNG sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 2 == 0:
            print(f"   {i + 1}/30s...", end="\r")

    print()
    logger.warning("⚠️  SearXNG chưa sẵn sàng sau 30s, tiếp tục (fallback ddgs)")
    return False


def start_asr() -> bool:
    """Khởi động ASR server ở cửa sổ CMD riêng."""
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

    logger.info("🚀 Khởi động ASR server (cửa sổ riêng)...")
    try:
        command = [str(ASR_PYTHON), str(ASR_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "ASR Server"] + command
        subprocess.Popen(command, cwd=str(ASR_DIR))
    except Exception as e:
        logger.error(f"❌ Không chạy được ASR: {e}")
        return False

    logger.info("⏳ Đợi ASR khởi động (load model có thể mất 30-60s)...")
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
    """Khởi động VieNeu-TTS server ở cửa sổ CMD riêng."""
    if is_vieneu_running():
        logger.success("✅ VieNeu-TTS đã chạy")
        return True

    if not PROJECT_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy Python project: {PROJECT_PYTHON}")
        logger.error("   Tạo venv: python -m venv venv")
        logger.error("   Cài dependency: pip install -r requirements.txt")
        return False

    if not VIENEU_SCRIPT.exists():
        logger.error(f"❌ Không tìm thấy script: {VIENEU_SCRIPT}")
        return False

    logger.info("🚀 Khởi động VieNeu-TTS server (cửa sổ riêng)...")
    try:
        command = [str(PROJECT_PYTHON), str(VIENEU_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "VieNeu-TTS Server"] + command
        subprocess.Popen(command, cwd=str(VIENEU_DIR))
    except Exception as e:
        logger.error(f"❌ Không chạy được VieNeu-TTS: {e}")
        return False

    logger.info("⏳ Đợi VieNeu-TTS khởi động (load model lần đầu 30-90s)...")
    for i in range(120):
        time.sleep(1)
        if is_vieneu_running():
            logger.success(f"✅ VieNeu-TTS sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 5 == 0:
            print(f"   {i + 1}/120s...", end="\r")

    print()
    logger.warning("⚠️  VieNeu-TTS chưa sẵn sàng sau 120s, tiếp tục...")
    logger.warning("   Kiểm tra cửa sổ 'VieNeu-TTS Server' để xem log chi tiết")
    return False


def check_mqtt() -> bool:
    """Kiểm tra Mosquitto broker (không tự start — dùng service)."""
    if is_mqtt_running():
        logger.success(f"✅ Mosquitto đang chạy ({MQTT_HOST}:{MQTT_PORT})")
        return True
    else:
        logger.warning(
            f"⚠️  Mosquitto chưa chạy ({MQTT_HOST}:{MQTT_PORT})"
        )
        logger.warning("   Chạy: net start mosquitto")
        return False


def load_config() -> dict:
    """Đọc config.yaml."""
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        logger.warning(f"⚠️  Không tìm thấy {config_path} — dùng default")
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Không đọc được config.yaml: {e}")
        return {}


# =====================================================
# MAIN
# =====================================================

def main():
    print()
    logger.info("═" * 50)
    logger.info("  🚀 XIAOZHI SERVER - START")
    logger.info("═" * 50)

    # Đọc config
    cfg = load_config()
    mqtt_enabled = cfg.get("mqtt", {}).get("enabled", False)

    # 1. Ollama
    logger.info("\n[1/6] Ollama...")
    start_ollama()

    # 2. SearXNG
    logger.info("\n[2/6] SearXNG...")
    start_searxng()

    # 3. ASR
    logger.info("\n[3/6] ASR server...")
    start_asr()

    # 4. VieNeu-TTS
    logger.info("\n[4/6] VieNeu-TTS server...")
    start_vieneu()

    # 5. Mosquitto (nếu MQTT enabled)
    logger.info("\n[5/6] Mosquitto MQTT...")
    if mqtt_enabled:
        check_mqtt()
    else:
        logger.info("⏭️  MQTT disabled trong config.yaml")

    # 6. FastAPI
    logger.info("\n[6/6] FastAPI server...")

    # ✅ Quyết định reload mode
    if mqtt_enabled:
        print()
        logger.warning("═" * 50)
        logger.warning("⚠️  MQTT ENABLED → RELOAD TẮT")
        logger.warning("═" * 50)
        logger.warning("Lý do: reload=True fork process con → mất event loop policy")
        logger.warning("       → aiomqtt crash NotImplementedError")
        logger.warning("")
        logger.warning("Muốn sửa code phải Ctrl+C và chạy lại thủ công")
        logger.warning("═" * 50)
        reload_mode = False
    else:
        logger.info("🔧 Reload mode: ON (tiện dev, Ctrl+S tự reload)")
        reload_mode = True

    logger.info("")
    logger.info("═" * 50)
    logger.info(f"  🌐 http://localhost:8000/chat")
    logger.info(f"  🌐 http://localhost:8000/admin")
    logger.info(f"  🔧 Reload: {'OFF' if not reload_mode else 'ON'}")
    logger.info(f"  📡 MQTT:   {'ENABLED' if mqtt_enabled else 'disabled'}")
    logger.info("═" * 50)
    logger.info("")

    # Chạy FastAPI
    if reload_mode:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            loop="asyncio",
        )
    else:
        # Tắt reload → policy giữ nguyên → MQTT OK
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            loop="asyncio",
            access_log=False,
        )


if __name__ == "__main__":
    main()

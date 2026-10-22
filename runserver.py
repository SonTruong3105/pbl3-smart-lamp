"""
Chạy CHỈ AI services trên PC (KHÔNG chạy FastAPI server).

Copy từ run.py gốc, sửa:
- Chỉ chạy: Ollama + SearXNG + ASR + VieNeu-TTS
- KHÔNG chạy: FastAPI + MQTT + UDP

Dùng cho mô hình:
    PC (nhà) ──── Tailscale ────→ Laptop ──── WiFi ────→ ESP32
    [AI services]                 [Server chính]
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import subprocess
import time
import socket
from pathlib import Path

import httpx
import yaml
from loguru import logger


# ═════════════════════════════════════════════════════════════
#  ĐƯỜNG DẪN (giống run.py gốc)
# ═════════════════════════════════════════════════════════════

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


def venv_python(venv: Path) -> Path:
    executable = "python.exe" if sys.platform == "win32" else "python"
    subdirectory = "Scripts" if sys.platform == "win32" else "bin"
    return venv / subdirectory / executable


PROJECT_PYTHON = venv_python(ROOT_DIR / "venv")
ASR_PYTHON = PROJECT_PYTHON


# ═════════════════════════════════════════════════════════════
#  CHECK FUNCTIONS
# ═════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════
#  START FUNCTIONS
# ═════════════════════════════════════════════════════════════

def start_ollama() -> bool:
    if is_ollama_running():
        logger.success("✅ Ollama đã chạy")
        return True

    logger.info("🚀 Khởi động Ollama (bind 0.0.0.0)...")
    import os
    env = os.environ.copy()
    env["OLLAMA_HOST"] = "0.0.0.0:11434"

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            env=env,
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
    logger.warning("⚠️  SearXNG chưa sẵn sàng, tiếp tục (fallback ddgs)")
    return False


def start_asr() -> bool:
    if is_asr_running():
        logger.success("✅ ASR server đã chạy")
        return True

    if not ASR_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy python ASR: {ASR_PYTHON}")
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

    logger.info("⏳ Đợi ASR khởi động (load model 30-60s)...")
    for i in range(90):
        time.sleep(1)
        if is_asr_running():
            logger.success(f"✅ ASR sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 5 == 0:
            print(f"   {i + 1}/90s...", end="\r")

    print()
    logger.warning("⚠️  ASR chưa sẵn sàng sau 90s")
    return False


def start_vieneu() -> bool:
    if is_vieneu_running():
        logger.success("✅ VieNeu-TTS đã chạy")
        return True

    if not PROJECT_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy Python project: {PROJECT_PYTHON}")
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

    logger.info("⏳ Đợi VieNeu-TTS khởi động (load model 30-90s)...")
    for i in range(120):
        time.sleep(1)
        if is_vieneu_running():
            logger.success(f"✅ VieNeu-TTS sẵn sàng sau {i + 1}s")
            return True
        if (i + 1) % 5 == 0:
            print(f"   {i + 1}/120s...", end="\r")

    print()
    logger.warning("⚠️  VieNeu-TTS chưa sẵn sàng sau 120s")
    return False


def print_ip_info():
    """In IP LAN + hướng dẫn kết nối từ laptop."""
    print()
    logger.info("═" * 60)
    logger.info("  📡 THÔNG TIN KẾT NỐI TỪ LAPTOP")
    logger.info("═" * 60)

    # IP LAN
    import socket as sock
    try:
        s = sock.socket(sock.AF_INET, sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "unknown"

    logger.info(f"  IP LAN:       http://{lan_ip}:11434-11436")
    logger.info(f"  IP Tailscale: http://<tailscale-ip>:11434-11436")
    logger.info(f"")
    logger.info(f"  Từ laptop, cấu hình config.yaml:")
    logger.info(f"    llm.ollama.url: \"http://<PC-TS-IP>:11434/api/chat\"")
    logger.info(f"    asr.url:        \"http://<PC-TS-IP>:11435/v1/audio/transcriptions\"")
    logger.info(f"    tts.vieneu.url: \"http://<PC-TS-IP>:11436\"")
    logger.info("═" * 60)


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

def main():
    print()
    logger.info("═" * 60)
    logger.info("  🚀 PC — AI SERVICES ONLY")
    logger.info("═" * 60)
    logger.info("  Chỉ chạy: Ollama + SearXNG + ASR + VieNeu-TTS")
    logger.info("  KHÔNG chạy: FastAPI + MQTT + UDP")
    logger.info("═" * 60)

    # 1. Ollama
    logger.info("\n[1/4] Ollama...")
    start_ollama()

    # 2. SearXNG
    logger.info("\n[2/4] SearXNG...")
    start_searxng()

    # 3. ASR
    logger.info("\n[3/4] ASR server...")
    start_asr()

    # 4. VieNeu-TTS
    logger.info("\n[4/4] VieNeu-TTS server...")
    start_vieneu()

    # Tổng kết
    print()
    logger.info("═" * 60)
    logger.success("  ✅ TẤT CẢ AI SERVICES ĐÃ CHẠY")
    logger.info("═" * 60)

    print_ip_info()

    logger.info("")
    logger.warning("  ⚠️  Nhấn Ctrl+C để dừng tất cả services")
    logger.info("")

    # Giữ process chính chạy
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print()
        logger.info("🛑 Đang dừng...")
        logger.info("(Các service con chạy trong cửa sổ riêng — đóng thủ công nếu cần)")


if __name__ == "__main__":
    main()
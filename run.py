import os
import sys
import asyncio
import subprocess
import time
import socket
import atexit
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# =====================================================
# 🚨 FIX LỖI MÔI TRƯỜNG (Phải đặt trước mọi import khác)
# =====================================================
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Fix Windows asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
import yaml
import uvicorn
from loguru import logger


# =====================================================
# MODEL LIFECYCLE: Nạp khi bật, nhả khi tắt
# =====================================================
_loaded_models = []


def unload_ollama_models():
    """Giải phóng VRAM bằng cách gửi keep_alive=0."""
    if not _loaded_models:
        return
    logger.info("\n🧹 [SHUTDOWN] Đang giải phóng VRAM (unload models)...")
    try:
        with httpx.Client(timeout=10.0) as client:
            for url, model in _loaded_models:
                try:
                    base = url.replace("/api/chat", "")
                    client.post(
                        f"{base}/api/generate",
                        json={"model": model, "keep_alive": 0},
                        timeout=5.0,
                    )
                    logger.info(f"   ✓ Đã nhả: {model}")
                except Exception as e:
                    logger.warning(f"   ⚠ Không nhả được {model}: {e}")
        logger.success("✅ [SHUTDOWN] Đã giải phóng VRAM.")
    except Exception as e:
        logger.warning(f"⚠ [SHUTDOWN] Lỗi unload: {e}")
    finally:
        _loaded_models.clear()


def _handle_exit_signal(signum, frame):
    unload_ollama_models()
    sys.exit(0)


atexit.register(unload_ollama_models)
signal.signal(signal.SIGINT, _handle_exit_signal)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _handle_exit_signal)


# =====================================================
# CẤU HÌNH ĐƯỜNG DẪN
# =====================================================
ROOT_DIR = Path(__file__).parent
os.chdir(ROOT_DIR)

ASR_DIR = ROOT_DIR / "asr"
ASR_SCRIPT = ASR_DIR / "chunkformer_server.py"
ASR_URL = "http://localhost:11435"

VIENEU_DIR = ROOT_DIR / "vieneu-server"
VIENEU_SCRIPT = VIENEU_DIR / "server.py"
VIENEU_URL = "http://localhost:11436"

OLLAMA_URL = "http://localhost:11434"
MQTT_HOST = "localhost"
MQTT_PORT = 1883


def venv_python(venv: Path) -> Path:
    executable = "python.exe" if sys.platform == "win32" else "python"
    subdirectory = "Scripts" if sys.platform == "win32" else "bin"
    return venv / subdirectory / executable


PROJECT_PYTHON = venv_python(ROOT_DIR / "venv")
ASR_PYTHON = PROJECT_PYTHON


# =====================================================
# HÀM CHECK PORT & TRẠNG THÁI
# =====================================================
def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_ollama_running() -> bool:
    return is_port_open(11434)


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
    return is_port_open(MQTT_PORT)


# =====================================================
# BLOCKING PRELOAD: Chỉ nạp 1 LLM chính để tối ưu VRAM
# =====================================================
def force_preload_ollama(cfg: dict):
    """Chỉ nạp duy nhất LLM chính từ config.yaml (tiết kiệm ~1.1GB VRAM so với nạp thêm model phụ)."""
    logger.info("⏳ [PRELOAD] Đang nạp mô hình chính vào VRAM...")

    llm_cfg = cfg.get("LLM", {}).get("hybrid", {}).get("ollama_chat", {})
    model = llm_cfg.get("model")
    if not model or not is_ollama_running():
        return

    url = llm_cfg.get("url", f"{OLLAMA_URL}/api/chat")
    ctx = int(llm_cfg.get("num_ctx", 4096))

    try:
        start = time.time()
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "keep_alive": -1,
                    "think": False,
                    "options": {
                        "num_predict": 1,
                        "num_ctx": ctx,
                        "num_gpu": 99,
                    },
                },
            )
            resp.raise_for_status()
        elapsed = time.time() - start

        _loaded_models.append((url, model))
        logger.success(
            f"✅ [PRELOAD] {model} (ctx={ctx}, KV=q8_0) sẵn sàng ({elapsed:.1f}s)"
        )
    except Exception as e:
        logger.warning(f"⚠ [PRELOAD] Không thể nạp {model}: {e}")

    logger.info("🚀 [PRELOAD] Hoàn tất! Đang bật Server...\n")


# =====================================================
# HÀM START CÁC SERVER PHỤ
# =====================================================
def start_ollama() -> bool:
    if is_ollama_running():
        logger.success("✅ Ollama đã chạy (lưu ý: để tối ưu VRAM, hãy đảm bảo Ollama bật Flash Attention)")
        return True

    logger.info("🚀 Khởi động Ollama (Flash Attention + KV Cache q8_0)...")
    try:
        env = os.environ.copy()
        env["OLLAMA_MAX_LOADED_MODELS"] = "1"
        env["OLLAMA_KEEP_ALIVE"] = "-1"
        env["OLLAMA_FLASH_ATTENTION"] = "1"
        env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"

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
    return False


def start_asr() -> bool:
    if is_asr_running():
        logger.success("✅ ASR server đã chạy")
        return True

    if not ASR_PYTHON.exists() or not ASR_SCRIPT.exists():
        logger.error("❌ Không tìm thấy file ASR")
        return False

    logger.info("🚀 Khởi động ASR server...")
    try:
        command = [str(ASR_PYTHON), str(ASR_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "ASR Server"] + command
        subprocess.Popen(command, cwd=str(ASR_DIR), env=os.environ.copy())
    except Exception as e:
        logger.error(f"❌ Không chạy được ASR: {e}")
        return False

    for i in range(90):
        time.sleep(1)
        if is_asr_running():
            logger.success(f"✅ ASR sẵn sàng sau {i + 1}s")
            return True
    return False


def start_vieneu() -> bool:
    if is_vieneu_running():
        logger.success("✅ VieNeu-TTS đã chạy")
        return True

    if not PROJECT_PYTHON.exists() or not VIENEU_SCRIPT.exists():
        logger.error("❌ Không tìm thấy file VieNeu-TTS")
        return False

    logger.info("🚀 Khởi động VieNeu-TTS server...")
    try:
        command = [str(PROJECT_PYTHON), str(VIENEU_SCRIPT)]
        if sys.platform == "win32":
            command = ["cmd", "/c", "start", "VieNeu-TTS Server"] + command
        subprocess.Popen(command, cwd=str(VIENEU_DIR), env=os.environ.copy())
    except Exception as e:
        logger.error(f"❌ Không chạy được VieNeu-TTS: {e}")
        return False

    for i in range(120):
        time.sleep(1)
        if is_vieneu_running():
            logger.success(f"✅ VieNeu-TTS sẵn sàng sau {i + 1}s")
            return True
    return False


def load_config() -> dict:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        config_path = ROOT_DIR / "server.yaml"
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
    logger.info(f"📁 Root: {ROOT_DIR.resolve()}")
    logger.info(f"🐍 Python: {sys.executable}")

    cfg = load_config()
    mqtt_enabled = cfg.get("mqtt", {}).get("enabled", False)

    logger.info("\n[1/3] Khởi động song song Ollama, ASR, VieNeu-TTS...")
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_ollama = pool.submit(start_ollama)
        f_asr = pool.submit(start_asr)
        f_tts = pool.submit(start_vieneu)
        f_ollama.result()
        f_asr.result()
        f_tts.result()

    logger.info("\n[2/3] Mosquitto MQTT...")
    if mqtt_enabled:
        if is_mqtt_running():
            logger.success(f"✅ Mosquitto đang chạy ({MQTT_HOST}:{MQTT_PORT})")
        else:
            logger.warning(f"⚠️  Mosquitto chưa chạy ({MQTT_HOST}:{MQTT_PORT})")
    else:
        logger.info("⏭️  MQTT disabled trong config.yaml")

    # Ghi nhận model chính để tự động giải phóng VRAM khi tắt server
    # (Warmup thực tế với system_prompt & num_keep do app/main.py thực hiện)
    ollama_cfg = cfg.get("LLM", {}).get("hybrid", {}).get("ollama_chat", {})
    if ollama_cfg.get("model"):
        _loaded_models.append(
            (ollama_cfg.get("url", f"{OLLAMA_URL}/api/chat"), ollama_cfg["model"])
        )

    logger.info("\n[3/3] FastAPI server...")
    logger.info("")
    logger.info("═" * 50)
    logger.info("  🌐 Local:  http://localhost:8000/chat")
    logger.info(f"  🌐 Public: {os.environ.get('PUBLIC_WS_URL', 'Chưa cấu hình')}")
    logger.info(f"  📡 MQTT:   {'ENABLED' if mqtt_enabled else 'disabled'}")
    logger.info("═" * 50)
    logger.info("")

    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            loop="asyncio",
            access_log=False,
            timeout_graceful_shutdown=10,
        )
    finally:
        unload_ollama_models()


if __name__ == "__main__":
    main()
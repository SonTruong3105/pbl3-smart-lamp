import os
import sys
import asyncio
import shutil
import subprocess
import time
import socket
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
import atexit
import signal

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
                    # Gửi keep_alive=0 để ép Ollama nhả model ngay lập tức
                    base = url.replace("/api/chat", "")
                    client.post(f"{base}/api/generate", 
                                json={"model": model, "keep_alive": 0}, 
                                timeout=5.0)
                    logger.info(f"   ✓ Đã nhả: {model}")
                except Exception as e:
                    logger.warning(f"   ⚠ Không nhả được {model}: {e}")
        logger.success("✅ [SHUTDOWN] Đã giải phóng VRAM.")
    except Exception as e:
        logger.warning(f"⚠ [SHUTDOWN] Lỗi unload: {e}")
    finally:
        _loaded_models.clear()

# Đăng ký dọn dẹp tự động khi Python thoát (fallback)
atexit.register(unload_ollama_models)
# =====================================================

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
OLLAMA_INTENT_URL = "http://localhost:11434"
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
def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0

def is_ollama_running() -> bool:
    return is_port_open(11434)

def is_intent_ollama_running() -> bool:
    return is_port_open(11437)

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
# BLOCKING PRELOAD: Nạp Model vào VRAM trước khi bật Uvicorn
# =====================================================
def force_preload_ollama():
    """Nạp sẵn model vào VRAM với keep_alive vô hạn (sẽ nhả khi tắt)."""
    import time
    logger.info("⏳ [PRELOAD] Đang nạp mô hình vào VRAM...")
    
    models = [
    (f"{OLLAMA_URL}/api/chat", "qwen3.5:4b-q4_K_M"),  # GIỮ NGUYÊN model
    (f"{OLLAMA_INTENT_URL}/api/chat", "qwen2.5:1.5b")   # GIỮ NGUYÊN intent
    ]
    
    for url, model in models:
        port = 11434 if "11434" in url else 11437
        if not is_port_open(port):
            continue
            
        try:
            start = time.time()
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                    "keep_alive": -1,   # Giữ vô hạn, nhưng sẽ nhả khi tắt server
                    "think": False,
                    "options": {"num_predict": 1, "num_ctx": 1024, "num_gpu": 99}
                })
                resp.raise_for_status()
            elapsed = time.time() - start
            
            # Đăng ký vào danh sách để dọn dẹp khi tắt
            _loaded_models.append((url, model))
            
            logger.success(f"✅ [PRELOAD] {model} đã sẵn sàng (mất {elapsed:.1f}s)")
        except Exception as e:
            logger.warning(f"⚠ [PRELOAD] Không thể nạp {model}: {e}")
    logger.info("🚀 [PRELOAD] Hoàn tất! Đang bật Server...\n")

# =====================================================
# HÀM START CÁC SERVER PHỤ
# =====================================================
def start_ollama() -> bool:
    if is_ollama_running():
        logger.success("✅ Ollama đã chạy")
        return True

    logger.info("🚀 Khởi động Ollama...")
    try:
        env = os.environ.copy()
        env["OLLAMA_MAX_LOADED_MODELS"] = "2"
        env["OLLAMA_KEEP_ALIVE"] = "-1"
        
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

def ensure_intent_ollama() -> bool:
    if is_intent_ollama_running():
        logger.success("✅ Intent Ollama (11437) đã chạy")
        return True

    logger.info("🚀 Khởi động Intent Ollama (Port 11437)...")
    ollama_exe = shutil.which("ollama")
    if not ollama_exe:
        for candidate in [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Ollama\ollama.exe"),
        ]:
            if os.path.exists(candidate):
                ollama_exe = candidate
                break

    if not ollama_exe:
        return False

    env = os.environ.copy()
    env["OLLAMA_HOST"] = "127.0.0.1:11437"
    env["OLLAMA_MODELS"] = os.environ.get("OLLAMA_INTENT_MODELS", r"D:\ollama_models_intent")
    env["OLLAMA_LOG_DIR"] = os.path.join(env["OLLAMA_MODELS"], "logs")
    env["OLLAMA_MAX_LOADED_MODELS"] = "2"
    env["OLLAMA_KEEP_ALIVE"] = "-1"

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    try:
        subprocess.Popen(
            [ollama_exe, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except Exception:
        return False

    for i in range(8):
        time.sleep(1)
        if is_intent_ollama_running():
            logger.success(f"✅ Intent Ollama sẵn sàng sau {i + 1}s")
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

    logger.info("\n[1/5] Ollama...")
    start_ollama()

    logger.info("\n[1.5/5] Intent Ollama (port 11437)...")
    try:
        ensure_intent_ollama()
    except Exception as e:
        logger.warning(f"⚠️ Intent Ollama skip: {e}")

    logger.info("\n[2/5] ASR server...")
    start_asr()

    logger.info("\n[3/5] VieNeu-TTS server...")
    start_vieneu()

    logger.info("\n[4/5] Mosquitto MQTT...")
    if mqtt_enabled:
        if is_mqtt_running():
            logger.success(f"✅ Mosquitto đang chạy ({MQTT_HOST}:{MQTT_PORT})")
        else:
            logger.warning(f"⚠️  Mosquitto chưa chạy ({MQTT_HOST}:{MQTT_PORT})")
    else:
        logger.info("⏭️  MQTT disabled trong config.yaml")

    # 🔥 GỌI PRELOAD TẠI ĐÂY (Chặn Server lại cho đến khi nạp xong)
    logger.info("\n[4.5/5] Làm nóng (Preload) AI Models...")
    force_preload_ollama()

    logger.info("\n[5/5] FastAPI server...")
    logger.info("")
    logger.info("═" * 50)
    logger.info(f"  🌐 Local: http://localhost:8000/chat")
    logger.info(f"  🌐 Public: {os.environ.get('PUBLIC_WS_URL', 'Chưa cấu hình')}")
    logger.info(f"  📡 MQTT:   {'ENABLED' if mqtt_enabled else 'disabled'}")
    logger.info("═" * 50)
    logger.info("")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        loop="asyncio",
        access_log=False,
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()
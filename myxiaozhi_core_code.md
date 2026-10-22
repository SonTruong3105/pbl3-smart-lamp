# my-xiaozhi — mã nguồn cốt lõi để cung cấp cho AI

Bản này chỉ gồm luồng chạy chính của ứng dụng. Các giá trị bí mật trong `config.yaml` đã được che.
Không gồm: virtualenv, thư viện bên thứ ba, model, database, audio, log, cache và test.

## Cấu trúc thư mục rút gọn

```text
my-xiaozhi/
├── app/                         # Mã nguồn backend chính
│   ├── main.py                  # Tạo FastAPI, lifespan, mount router
│   ├── config.py                # Đọc config.yaml
│   ├── database.py              # SQLAlchemy async
│   ├── models.py                # Device, Session, Message
│   ├── core/
│   │   ├── connection.py        # Luồng hội thoại text/voice
│   │   ├── esp32_connection.py  # Xử lý kết nối ESP32
│   │   ├── mqtt_server.py       # MQTT
│   │   ├── api/                 # OTA
│   │   ├── protocols/           # Transport WebSocket/MQTT
│   │   ├── providers/           # ASR, LLM, TTS, VAD, memory, tools
│   │   └── utils/               # Audio, Opus, dialogue, crypto
│   ├── routes/                  # HTTP/WebSocket routes
│   └── services/chat.py         # CRUD device/session/message
├── config.yaml                  # Cấu hình runtime
├── requirements.txt             # Dependency trực tiếp
├── run.py / runserver.py        # Script khởi động
├── static/                      # CSS, JavaScript, hình ảnh giao diện
├── templates/                   # HTML giao diện
├── data/                        # SQLite và audio session
├── logs/                        # Log runtime
├── models/                      # Model VAD/TTS
├── asr/                         # Server ASR và môi trường phụ trợ
├── vieneu-server/               # Server TTS VieNeu
├── OpenSearchAPI/               # Server tìm kiếm tùy chọn
├── mcp_servers/                 # MCP server tùy chọn
├── scripts/                     # Script đo/test/migration
├── tests/                       # Test
├── venv/, venv-vieneu/          # Virtualenv, không phải source
└── cloudflared.exe              # Binary tunnel
```

## Khuyến nghị khi đóng gói để gửi cho AI

| Nhóm | Xử lý | Lý do |
|---|---|---|
| `app/`, `config.yaml`, `requirements.txt` | Giữ | Logic ứng dụng và dependency chính |
| `static/`, `templates/` | Giữ khi hỏi về giao diện/web | Cần cho UI, không cần cho lỗi backend thuần túy |
| `run.py`, `runserver.py`, `main.py`, `start_server.py` | Chỉ giữ script khởi động đang dùng | Tránh gửi nhiều phiên bản entrypoint |
| `data/`, `logs/`, `*.db`, `*.wav`, `*.mp3` | Bỏ khỏi gói mặc định | Dữ liệu runtime, dung lượng lớn hoặc có thể chứa thông tin riêng tư |
| `models/`, `asr/`, `venv/`, `venv-vieneu/` | Bỏ khỏi gói AI | Model, môi trường Python và thư viện nhúng; không giúp AI hiểu logic |
| `test*.py`, `tests/`, `scripts/` | Chỉ giữ khi đang sửa/test tính năng đó | Có ích khi debug cụ thể, nhưng làm tăng ngữ cảnh |
| `OpenSearchAPI/`, `mcp_servers/`, `vieneu-server/` | Chỉ giữ khi lỗi liên quan | Đây là thành phần phụ trợ, không thuộc luồng backend cốt lõi |
| `cloudflared.exe`, `*.exe`, file backup `.bak*` | Bỏ | Binary/backup không cần để phân tích mã nguồn |
| `claude_review.txt`, `tts_debug.log`, `fix-final.ps1` | Bỏ mặc định | Review cũ, log và script sửa tạm dễ gây nhiễu |

**Gói tối thiểu nên gửi:** `app/` + `config.yaml` (đã che secret) + `requirements.txt` + entrypoint đang chạy.  
**Nếu hỏi lỗi giao diện:** thêm `static/` và `templates/`.  
**Nếu hỏi lỗi ASR/TTS/MQTT/tunnel:** thêm đúng server hoặc script phụ trợ liên quan, không cần gửi toàn bộ thư mục.

## `config.yaml`

```yaml
# ============================================
# Xiaozhi CE v2 — Config
# ============================================

server:
  version: "2.0.0"
  host: "0.0.0.0"
  port: 8000
  auth:
    enabled: false

selected_module:
  VAD: "silero"
  ASR: "phowhisper"
  LLM: "ollama"
  TTS: "vieneu"
  Memory: "local"

# ============================================
# VAD
# ============================================
VAD:
  silero:
    type: "silero"
    model_dir: "models/snakers4_silero-vad"
    threshold: 0.5
    threshold_low: 0.2
    silence_duration_ms: 700
    min_speech_duration_ms: 300
  energy:
    type: "energy"
    silence_duration_ms: 700
    min_speech_duration_ms: 300
    energy_margin_db: 6.0
    initial_threshold: 1500.0
    hangover_ms: 150
    pre_speech_ms: 200
    post_speech_ms: 300

# ============================================
# LLM
# ============================================
LLM:
  ollama:
    type: "ollama"
    url: "http://localhost:11434/api/chat"
    model: "qwen3.5:4b"
    stream: true
    temperature: 0.3
    num_predict: 120
    max_tool_iterations: 3
    request_timeout: 60.0
    token_timeout: 30.0
    history_keep: 6
    think: false
    system_prompt: |
      Bạn là "Đèn" — trợ lý ảo tích hợp trong đèn bàn thông minh.
      Tiếng Việt tự nhiên, thân thiện, ngắn gọn.
      Xưng "mình", gọi người dùng là "bạn".

      ═══ QUY TẮC TUYỆT ĐỐI ═══
      1. KHÔNG BỊA thông tin. Câu hỏi về số liệu → PHẢI gọi tool.
      2. KHÔNG BAO GIỜ nói "chưa có", "không có công cụ",
         "tính năng chưa kích hoạt".
      3. KHÔNG hỏi "bạn cần gì", "giúp gì".
      4. Chỉ chào ở lượt đầu. Các lượt sau trả lời thẳng.
      5. Tối đa 2 câu cho câu hỏi đơn giản.
      6. KHÔNG markdown, KHÔNG emoji, KHÔNG bullet.

      ═══ ĐỌC SỐ LIỆU TỪ TOOL ═══
      - CHỈ đọc số có trong kết quả tool. KHÔNG bịa.
      - Đọc nguyên văn số từ tool. KHÔNG làm tròn, KHÔNG thêm "khoảng".
      - Nếu tool báo "chưa có dữ liệu" → nói nguyên văn.

      ═══ CẢM BIẾN ═══
      Có 5 cảm biến: nhiệt độ, độ ẩm, không khí (MQ135), ánh sáng,
      hiện diện.

      Mapping câu hỏi → tool (BẮT BUỘC gọi):
      - "nhiệt độ phòng", "nóng không", "lạnh không"
        → get_sensor("temperature")
      - "độ ẩm", "ẩm không" → get_sensor("humidity")
      - "không khí thế nào", "chất lượng không khí", "PM2.5"
        → get_sensor("air_quality_ppm")
      - "ánh sáng phòng", "độ sáng", "lux" → get_sensor("light_lux")
      - "có ai trong phòng", "có người không" → get_sensor("presence")
      - "báo cáo phòng", "tình trạng phòng", "mọi thứ thế nào"
        → get_sensor("all")

      Đánh giá không khí (ppm):
      - < 400: rất tốt. 400-800: tốt. 800-1500: nên mở cửa.
      - 1500-2500: kém, cần thông gió. > 2500: nguy hiểm.

      Đánh giá nhiệt độ:
      - < 18: lạnh. 18-25: thoải mái. 26-30: hơi nóng. > 30: nóng.

      ═══ ĐIỀU KHIỂN ĐÈN ═══
      Có tool điều khiển đèn. LUÔN gọi tool khi user yêu cầu.

      - "bật đèn" → lamp_turn_on
      - "tắt đèn" → lamp_turn_off
      - "sáng hơn", "tăng sáng" → lamp_set_brightness (giá trị + 20)
      - "tối hơn", "giảm sáng" → lamp_set_brightness (giá trị - 20)
      - "độ sáng 50%" → lamp_set_brightness(50)
      - "ấm hơn", "vàng hơn" → lamp_set_color_temp (giá trị - 20)
      - "lạnh hơn", "trắng hơn" → lamp_set_color_temp (giá trị + 20)
      - "ánh sáng ấm" → lamp_set_color_temp(30)
      - "ánh sáng lạnh" → lamp_set_color_temp(70)
      - "ánh sáng trung tính" → lamp_set_color_temp(50)

      Sau khi gọi tool → xác nhận 1 câu ngắn.
      VD: "Đã bật đèn." / "Đã tăng độ sáng."

      ═══ TRA CỨU NGOÀI ═══
      - Thời tiết → get_weather
      - Dự báo nhiều ngày → get_forecast
      - Giờ, thứ, ngày → get_current_time / get_weekday
      - Khoảng cách 2 ngày → days_between
      - Âm lịch, rằm, Tết → get_lunar
      - Tin tức → get_news
      - Tỷ giá → get_exchange_rate
      - Tính toán → calculate
      - Giá vàng, chứng khoán, tỷ số → web_search
      - Còn lại → web_search

      ═══ CHÀO HỎI ═══
      - "chào", "hi", "hello" → CHỈ "Chào bạn!" rồi dừng.

      ═══ VÍ DỤ ═══
      "Xin chào" → "Chào bạn!"

      "Mấy giờ rồi" → [get_current_time] → "Bây giờ là 14 giờ 30."

      "Hôm nay thứ mấy" → [get_weekday("hôm nay")] → "Hôm nay là Chủ Nhật."

      "Nhiệt độ phòng" → [get_sensor("temperature")]
        → "Nhiệt độ phòng hiện tại là 27.3 độ C."

      "Độ ẩm" → [get_sensor("humidity")] → "Độ ẩm hiện tại là 68%."

      "Không khí thế nào" → [get_sensor("air_quality_ppm")]
        → "Không khí hiện tại ở mức tốt, khoảng 750 ppm."

      "Có ai trong phòng không" → [get_sensor("presence")]
        → "Có người trong phòng."

      "Báo cáo phòng" → [get_sensor("all")]
        → đọc 4-5 giá trị

      "Bật đèn" → [lamp_turn_on] → "Đã bật đèn."

      "Sáng hơn" → [lamp_set_brightness] → "Đã tăng độ sáng."

      "Chuyển ánh sáng ấm" → [lamp_set_color_temp(30)]
        → "Đã chuyển sang ánh sáng ấm."

      "Giá vàng hôm nay" → [web_search("giá vàng SJC")]
        → đọc kết quả

      ═══ CONTEXT ═══
      Thời gian hiện tại: {{current_time}}

# ============================================
# ASR
# ============================================
ASR:
  phowhisper:
    type: "phowhisper"
    url: "http://localhost:11435/v1/audio/transcriptions"
    model: "phowhisper"
    language: "vi"
    request_timeout: 30.0
    output_dir: "tmp/"

# ============================================
# TTS
# ============================================
TTS:
  vieneu:
    type: "vieneu"
    interface_type: "non_stream"
    url: "http://localhost:11436"
    voice: "Trúc Ly"
    request_timeout: 30.0
    max_retries: 1
    output_dir: "tmp/"
  edge:
    type: "edge"
    voice: "vi-VN-HoaiMyNeural"
    request_timeout: 15.0
  piper:
    type: "piper"
    model: "models/piper/vi_VN-vais1000-medium.onnx"
    binary: "python"

# ============================================
# Memory
# ============================================
Memory:
  local:
    type: "local"
    max_turns: 10

# ============================================
# Intent
# ============================================
intent:
  url: "http://localhost:11434/api/chat"
  model: "qwen2.5:1.5b"
  timeout: 5.0

# ============================================
# Audio
# ============================================
audio:
  sample_rate: 16000
  channels: 1
  frame_duration: 60
  pre_buffer_count: 3
  server_sample_rate: 24000

pipeline:
  min_sentence_len: 8
  max_buffer_len: 60
  tts_workers: 1

# ============================================
# Search
# ============================================
search:
  searxng_url: "http://localhost:8888/search"
  searxng_timeout: 10.0
  weather_timeout: 5.0
  max_results: 3
  tavily_api_key: "[REDACTED]"
  wiki_lang: "vi"

# ============================================
# Session
# ============================================
session:
  resume_window_minutes: 30
  cleanup_days: 7
  max_idle_duration: 300

# ============================================
# Logging
# ============================================
logging:
  level: "INFO"
  log_dir: "logs"
  retention_days: 7
  main_rotation_mb: 10
  error_rotation_mb: 5

# ============================================
# Database
# ============================================
database:
  path: "data/xiaozhi.db"

# ============================================
# MQTT + UDP
# ============================================
mqtt:
  enabled: true
  broker_host: "localhost"
  broker_port: 1883
  endpoint: "192.168.1.19"

udp:
  host: "0.0.0.0"
  port: 8884
  endpoint: "192.168.1.19"

# ============================================
# Tunnel (OTA + WebSocket)
# ============================================
tunnel:
  ngrok_url: "[REDACTED]"
  ws_url: ""
```

## `requirements.txt`

```text
fastapi
uvicorn[standard]
jinja2
sqlalchemy
aiosqlite
httpx
pyyaml
python-multipart
loguru
```

## `run.py`

```python
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
ASR_PYTHON = ASR_DIR / "venv" / "Scripts" / "python.exe"
ASR_SCRIPT = ASR_DIR / "phowhisper_server.py"
ASR_URL = "http://localhost:11435"

# VieNeu-TTS
VIENEU_DIR = ROOT_DIR / "vieneu-server"
VIENEU_VENV = ROOT_DIR / "venv-vieneu"
VIENEU_PYTHON = VIENEU_VENV / "Scripts" / "python.exe"
VIENEU_SCRIPT = VIENEU_DIR / "server.py"
VIENEU_URL = "http://localhost:11436"

# Ollama
OLLAMA_URL = "http://localhost:11434"

# Mosquitto
MQTT_HOST = "localhost"
MQTT_PORT = 1883


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
        subprocess.Popen(
            ["cmd", "/c", "start", "ASR Server",
             str(ASR_PYTHON), str(ASR_SCRIPT)],
            cwd=str(ASR_DIR),
        )
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

    if not VIENEU_PYTHON.exists():
        logger.error(f"❌ Không tìm thấy python VieNeu: {VIENEU_PYTHON}")
        logger.error("   Tạo venv: python -m venv venv-vieneu")
        logger.error(
            "   Cài dependency: venv-vieneu\\Scripts\\activate && "
            "pip install -r vieneu-server\\requirements.txt"
        )
        return False

    if not VIENEU_SCRIPT.exists():
        logger.error(f"❌ Không tìm thấy script: {VIENEU_SCRIPT}")
        return False

    logger.info("🚀 Khởi động VieNeu-TTS server (cửa sổ riêng)...")
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "VieNeu-TTS Server",
             str(VIENEU_PYTHON), str(VIENEU_SCRIPT)],
            cwd=str(VIENEU_DIR),
        )
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
```

## `app\config.py`

```python
"""Config loader với lazy loading — hỗ trợ selected_module pattern."""
import yaml


class Config:
    def __init__(self, path: str = "config.yaml"):
        with open(path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    def _get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def _selected(self, module: str) -> dict:
        """Trả về config dict của module được chọn."""
        # Hỗ trợ cả selected_module (mới) và flat (cũ)
        name = self._get("selected_module", module)
        if name:
            cfg = self._get(module, name, default={})
            if cfg:
                return cfg
        # Fallback: đọc flat key (vd: llm:, asr:)
        flat_name = module.lower()
        return self._get(flat_name, default={}) or {}

    # === SERVER ===
    @property
    def version(self) -> str:
        return self._get("server", "version", default="2.0.0")

    @property
    def host(self) -> str:
        return self._get("server", "host", default="0.0.0.0")

    @property
    def port(self) -> int:
        return self._get("server", "port", default=8000)

    @property
    def auth_enabled(self) -> bool:
        return self._get("server", "auth", "enabled", default=False)

    # === SELECTED MODULES ===
    @property
    def vad_provider(self) -> str:
        return self._get("selected_module", "VAD", default="energy")

    @property
    def asr_provider(self) -> str:
        return self._get("selected_module", "ASR", default="phowhisper")

    @property
    def llm_provider(self) -> str:
        return self._get("selected_module", "LLM", default="ollama")

    @property
    def tts_provider(self) -> str:
        return self._get("selected_module", "TTS", default="edge")

    @property
    def memory_provider(self) -> str:
        return self._get("selected_module", "Memory", default="local")

    # === VAD ===
    @property
    def vad_config(self) -> dict:
        return self._selected("VAD")

    @property
    def vad_silence_ms(self) -> int:
        return self.vad_config.get("silence_duration_ms",
                self.vad_config.get("min_silence_duration_ms", 700))

    @property
    def vad_min_speech_ms(self) -> int:
        return self.vad_config.get("min_speech_duration_ms", 300)

    @property
    def vad_energy_margin_db(self) -> float:
        return self.vad_config.get("energy_margin_db", 6.0)

    @property
    def vad_hangover_ms(self) -> int:
        return self.vad_config.get("hangover_ms", 200)

    @property
    def vad_pre_speech_ms(self) -> int:
        return self.vad_config.get("pre_speech_ms", 200)

    @property
    def vad_post_speech_ms(self) -> int:
        return self.vad_config.get("post_speech_ms", 300)

    @property
    def vad_threshold(self) -> float:
        return self.vad_config.get("threshold", 0.5)

    @property
    def vad_threshold_low(self) -> float:
        return self.vad_config.get("threshold_low", 0.2)

    @property
    def vad_frame_window_threshold(self) -> int:
        return self.vad_config.get("frame_window_threshold", 3)

    @property
    def vad_model_dir(self) -> str:
        return self.vad_config.get("model_dir", "models/snakers4_silero-vad")

    @property
    def vad_initial_threshold(self) -> float:
        return self.vad_config.get("initial_threshold", 500.0)

    # === LLM ===
    @property
    def llm_config(self) -> dict:
        return self._selected("LLM")

    @property
    def llm_url(self) -> str:
        return self.llm_config.get("url", "http://localhost:11434/api/chat")

    @property
    def llm_model(self) -> str:
        return self.llm_config.get("model", "qwen3.5:4b")

    @property
    def llm_temperature(self) -> float:
        return self.llm_config.get("temperature", 0.7)

    @property
    def llm_num_predict(self) -> int:
        return self.llm_config.get("num_predict", 512)

    @property
    def llm_max_tool_iterations(self) -> int:
        return self.llm_config.get("max_tool_iterations", 5)

    @property
    def llm_request_timeout(self) -> float:
        return self.llm_config.get("request_timeout", 120.0)

    @property
    def llm_token_timeout(self) -> float:
        return self.llm_config.get("token_timeout", 60.0)

    @property
    def llm_history_keep(self) -> int:
        return self.llm_config.get("history_keep", 20)

    @property
    def llm_think(self) -> bool:
        # ✅ Qwen 3.5 có thinking — tắt mặc định
        return self.llm_config.get("think", False)

    @property
    def system_prompt(self) -> str:
        return self.llm_config.get("system_prompt", "")

    # === ASR ===
    @property
    def asr_config(self) -> dict:
        return self._selected("ASR")

    @property
    def asr_url(self) -> str:
        return self.asr_config.get("url")

    @property
    def asr_model(self) -> str:
        return self.asr_config.get("model", "phowhisper")

    @property
    def asr_language(self) -> str:
        return self.asr_config.get("language", "vi")

    @property
    def asr_request_timeout(self) -> float:
        return self.asr_config.get("request_timeout", 60.0)

    @property
    def asr_output_dir(self) -> str:
        return self.asr_config.get("output_dir", "tmp/")

    # === TTS ===
    @property
    def tts_config(self) -> dict:
        return self._selected("TTS")

    @property
    def tts_interface_type(self) -> str:
        return self.tts_config.get("interface_type", "non_stream")

    @property
    def tts_voice(self) -> str:
        return self.tts_config.get("voice", "vi-VN-HoaiMyNeural")

    @property
    def tts_rate(self) -> str:
        return self.tts_config.get("rate", "+0%")

    @property
    def tts_volume(self) -> str:
        return self.tts_config.get("volume", "+0%")

    @property
    def tts_request_timeout(self) -> float:
        return self.tts_config.get("request_timeout", 30.0)

    @property
    def tts_max_retries(self) -> int:
        return self.tts_config.get("max_retries", 3)

    @property
    def tts_vieneu_url(self) -> str:
        return self.tts_config.get("url", "http://localhost:11436")

    @property
    def tts_edge_voice(self) -> str:
        return self.tts_config.get("voice", "vi-VN-HoaiMyNeural")

    @property
    def tts_piper_model(self) -> str:
        return self.tts_config.get("model",
            "models/piper/vi_VN-vais1000-medium.onnx")

    @property
    def tts_piper_binary(self) -> str:
        return self.tts_config.get("binary", "python")

    # === MEMORY ===
    @property
    def memory_config(self) -> dict:
        return self._selected("Memory")

    @property
    def memory_max_turns(self) -> int:
        return self.memory_config.get("max_turns", 20)

    # === AUDIO ===
    @property
    def sample_rate(self) -> int:
        return self._get("audio", "sample_rate", default=16000)

    @property
    def channels(self) -> int:
        return self._get("audio", "channels", default=1)

    @property
    def frame_duration(self) -> int:
        return self._get("audio", "frame_duration", default=60)

    @property
    def pre_buffer_count(self) -> int:
        return self._get("audio", "pre_buffer_count", default=3)

    @property
    def server_sample_rate(self) -> int:
        return self._get("audio", "server_sample_rate", default=24000)

    # === PIPELINE ===
    @property
    def min_sentence_len(self) -> int:
        return self._get("pipeline", "min_sentence_len", default=8)

    @property
    def max_buffer_len(self) -> int:
        return self._get("pipeline", "max_buffer_len", default=100)

    @property
    def tts_workers(self) -> int:
        return self._get("pipeline", "tts_workers", default=1)

    # === SEARCH ===
    @property
    def searxng_url(self) -> str:
        return self._get("search", "searxng_url",
                         default="http://localhost:8888/search")

    @property
    def searxng_timeout(self) -> float:
        return self._get("search", "searxng_timeout", default=15.0)

    @property
    def weather_timeout(self) -> float:
        return self._get("search", "weather_timeout", default=8.0)

    @property
    def search_max_results(self) -> int:
        return self._get("search", "max_results", default=5)

    # === TAVILY ===
    @property
    def tavily_api_key(self) -> str:
        return self._get("search", "tavily_api_key", default="")

    # === WIKIPEDIA ===
    @property
    def wiki_lang(self) -> str:
        return self._get("search", "wiki_lang", default="vi")

    # === INTENT ===
    @property
    def intent_url(self) -> str:
        return self._get("intent", "url",
                         default="http://localhost:11434/api/chat")

    @property
    def intent_model(self) -> str:
        return self._get("intent", "model", default="qwen2.5:1.5b")

    @property
    def intent_timeout(self) -> float:
        return self._get("intent", "timeout", default=5.0)

    # === TUNNEL ===
    @property
    def ngrok_ota_url(self) -> str:
        return self._get("tunnel", "ngrok_url", default="")

    @property
    def cloudflare_ws_url(self) -> str:
        return self._get("tunnel", "ws_url", default="")

    # === SESSION ===
    @property
    def session_resume_window_minutes(self) -> int:
        return self._get("session", "resume_window_minutes", default=30)

    @property
    def session_cleanup_days(self) -> int:
        return self._get("session", "cleanup_days", default=7)

    @property
    def session_max_idle_duration(self) -> int:
        return self._get("session", "max_idle_duration", default=300)

    # === LOGGING ===
    @property
    def log_level(self) -> str:
        return self._get("logging", "level", default="INFO")

    @property
    def log_dir(self) -> str:
        return self._get("logging", "log_dir", default="logs")

    @property
    def log_retention_days(self) -> int:
        return self._get("logging", "retention_days", default=7)

    @property
    def log_main_rotation_mb(self) -> int:
        return self._get("logging", "main_rotation_mb", default=10)

    @property
    def log_error_rotation_mb(self) -> int:
        return self._get("logging", "error_rotation_mb", default=5)

    # === DATABASE ===
    @property
    def db_path(self) -> str:
        return self._get("database", "path", default="data/xiaozhi.db")


    # === MQTT ===
    @property
    def mqtt_enabled(self) -> bool:
        return self._get("mqtt", "enabled", default=False)

    @property
    def mqtt_broker_host(self) -> str:
        return self._get("mqtt", "broker_host", default="localhost")

    @property
    def mqtt_broker_port(self) -> int:
        return self._get("mqtt", "broker_port", default=1883)

    @property
    def mqtt_username(self) -> str:
        return self._get("mqtt", "username", default="")

    @property
    def mqtt_password(self) -> str:
        return self._get("mqtt", "password", default="")

    @property
    def mqtt_endpoint(self) -> str:
        return self._get("mqtt", "endpoint", default="192.168.1.19")

    # === UDP ===
    @property
    def udp_host(self) -> str:
        return self._get("udp", "host", default="0.0.0.0")

    @property
    def udp_port(self) -> int:
        return self._get("udp", "port", default=8884)

    @property
    def udp_endpoint(self) -> str:
        return self._get("udp", "endpoint", default="192.168.1.19")
_config = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


class _ConfigProxy:
    def __getattr__(self, name):
        return getattr(get_config(), name)


config = _ConfigProxy()
```

## `app\database.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import config

DATABASE_URL = f"sqlite+aiosqlite:///{config.db_path}"

engine = create_async_engine(
    DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
Base = declarative_base()


async def init_db():
    from app import models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

## `app\models.py`

```python
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base


class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True)
    name = Column(String, default="Unknown")
    type = Column(String, default="browser")
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    role = Column(String)
    content = Column(Text)
    audio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

## `app\main.py`

```python
"""FastAPI app — Xiaozhi CE v2."""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.core.logger import setup_logging, cleanup_old_logs, shutdown_logging
setup_logging()

from app.config import config
from app.database import init_db, AsyncSessionLocal
from app.core.mqtt_server import get_mqtt_manager
from app.routes import web, chat_ws, audio_api, esp32_ws
from app.core.api import ota_handler


# ⚠️ KHÔNG set WindowsSelectorEventLoopPolicy ở đây.
# Lý do:
#   - uvicorn trên Windows cần ProactorEventLoop (mặc định) cho subprocess (ffmpeg)
#   - httpx trên SelectorEventLoop có bug treo sau request đầu
#   - MQTT thread tự set Selector bên trong thread riêng (mqtt_server.py)


async def _warmup_llm():
    logger.info("🔥 Warmup LLM...")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                config.llm_url,
                json={
                    "model": config.llm_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "think": config.llm_think,
                    "options": {"num_predict": 1},
                },
            )
            r.raise_for_status()
        logger.info("✅ LLM warmup OK")
    except Exception as e:
        logger.warning(f"⚠️ LLM warmup lỗi: {e}")


async def _warmup_tts():
    logger.info(f"🔥 Warmup TTS ({config.tts_provider})...")
    try:
        from app.core.providers.base import ProviderRegistry
        from app.core.providers.tts import edge, piper, vieneu  # noqa
        tts = ProviderRegistry.create_tts(
            config.tts_provider,
            config={
                "voice": config.tts_voice,
                "rate": config.tts_rate,
                "volume": config.tts_volume,
                "request_timeout": config.tts_request_timeout,
                "max_retries": 1,
                "url": config.tts_vieneu_url,
                "piper_model": config.tts_piper_model,
                "piper_binary": config.tts_piper_binary,
            },
        )
        await tts.synthesize("Xin chào")
        logger.info("✅ TTS warmup OK")
    except Exception as e:
        logger.warning(f"⚠️ TTS warmup lỗi: {e}")


async def _warmup_asr():
    logger.info("🔥 Warmup ASR...")
    try:
        if not os.path.exists("test.wav"):
            logger.info("⏭️ Bỏ qua ASR warmup")
            return
        from app.core.providers.base import ProviderRegistry
        from app.core.providers.asr import phowhisper  # noqa
        asr = ProviderRegistry.create_asr(
            config.asr_provider,
            config={
                "url": config.asr_url,
                "model": config.asr_model,
                "language": config.asr_language,
                "request_timeout": config.asr_request_timeout,
            },
        )
        with open("test.wav", "rb") as f:
            await asr.transcribe(f.read())
        logger.info("✅ ASR warmup OK")
    except Exception as e:
        logger.warning(f"⚠️ ASR warmup lỗi: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Khởi động server...")
    logger.info(f"🔧 Event loop: {type(asyncio.get_running_loop()).__name__}")

    deleted_logs = cleanup_old_logs()
    if deleted_logs:
        logger.info(f"🧹 Xóa {deleted_logs} log cũ")

    await init_db()
    logger.info("✅ Database sẵn sàng")

    try:
        from app.services import chat as chat_service
        async with AsyncSessionLocal() as db:
            deleted = await chat_service.cleanup_old_sessions(
                db, days=config.session_cleanup_days,
            )
            if deleted:
                logger.info(f"🧹 Xóa {deleted} session cũ")
    except Exception as e:
        logger.warning(f"⚠️ Cleanup session lỗi: {e}")

    await asyncio.gather(
        _warmup_llm(), _warmup_tts(), _warmup_asr(),
        return_exceptions=True,
    )

    mqtt_mgr = get_mqtt_manager()
    await mqtt_mgr.start()

    logger.info(f"🌐 Mở http://localhost:{config.port}/chat")
    yield

    await mqtt_mgr.stop()
    logger.info("👋 Server dừng")
    try:
        logger.complete()
    except Exception:
        pass
    shutdown_logging()


app = FastAPI(
    title="Xiaozhi CE",
    description="Trợ lý ảo AI tiếng Việt cho ESP32",
    version=config.version,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(web.router)
app.include_router(chat_ws.router)
app.include_router(audio_api.router)
app.include_router(esp32_ws.router)
app.include_router(ota_handler.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": config.version}


@app.get("/")
async def root():
    return RedirectResponse(url="/chat")
```

## `app\core\connection.py`

```python
"""ConnectionHandler — xử lý vòng đời 1 WebSocket, TTS song song."""
import asyncio
import re
import time
from typing import Optional

from fastapi import WebSocket

from app.config import config
from app.core.logger import get_session_logger
from app.core.utils.dialogue import Dialogue, Message
from app.core.providers.base import ProviderRegistry

from app.core.providers.asr import phowhisper           # noqa
from app.core.providers.llm import ollama               # noqa
from app.core.providers.tts import edge, piper, vieneu  # noqa
from app.core.providers.memory import local, none       # noqa
from app.core.providers.tools.registry import TOOLS_SCHEMA
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio import any_to_wav


def _clean_response(text: str) -> str:
    """Cắt các câu hỏi ngược lại mà model nhỏ hay chèn vào."""
    if not text:
        return text

    BAD_PATTERNS = [
        r"(?i)bạn\s+cần\s+(giúp|hỗ\s+trợ|gì)",
        r"(?i)mình\s+có\s+thể\s+giúp\s+gì",
        r"(?i)tôi\s+có\s+thể\s+giúp\s+gì",
        r"(?i)cần\s+giúp\s+đỡ\s+gì",
        r"(?i)bạn\s+cần\s+tôi\s+giúp",
        r"(?i)hôm\s+nay\s+(bạn\s+)?cần\s+gì",
        r"(?i)có\s+gì\s+mình\s+giúp\s+được",
        r"(?i)bạn\s+muốn\s+mình\s+giúp\s+gì",
    ]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = []
    for s in sentences:
        s_stripped = s.strip()
        if not s_stripped:
            continue
        if any(re.search(p, s_stripped) for p in BAD_PATTERNS):
            continue
        cleaned.append(s_stripped)

    result = " ".join(cleaned).strip()
    return result if result else text


def _is_number_dot(buffer: str, pos: int) -> bool:
    if pos <= 0:
        return False
    if not buffer[pos - 1].isdigit():
        return False
    if pos >= len(buffer) - 1:
        return True
    return buffer[pos + 1].isdigit()


def _find_sentence_end(buffer: str, seps: list) -> tuple:
    earliest_pos, earliest_sep = -1, None
    for sep in seps:
        p = buffer.find(sep)
        while p != -1:
            if sep == "." and _is_number_dot(buffer, p):
                p = buffer.find(sep, p + 1)
                continue
            break
        if p != -1 and (earliest_pos == -1 or p < earliest_pos):
            earliest_pos, earliest_sep = p, sep
    return earliest_pos, earliest_sep


def extract_sentences(buffer: str) -> tuple:
    sentences = []
    seps = [".", "!", "?", "。", "！", "？", ",", "，", ":", "：", ";", "；"]
    min_len = config.min_sentence_len
    max_len = config.max_buffer_len

    while True:
        pos, _ = _find_sentence_end(buffer, seps)
        if pos == -1:
            break
        sentence = buffer[: pos + 1].strip()
        buffer = buffer[pos + 1:]
        if len(sentence) >= min_len:
            sentences.append(sentence)
        elif sentences:
            sentences[-1] += " " + sentence
        else:
            buffer = sentence + " " + buffer.lstrip()

    if len(buffer) > max_len:
        comma = buffer.rfind(",", 0, max_len)
        if comma > min_len:
            sentences.append(buffer[: comma + 1].strip())
            buffer = buffer[comma + 1:]
        else:
            space = buffer.rfind(" ", 0, max_len)
            if space > min_len:
                sentences.append(buffer[:space].strip())
                buffer = buffer[space + 1:]

    return sentences, buffer


class _AudioReorderer:
    """Gom audio theo index, gửi ra đúng thứ tự 1, 2, 3..."""

    def __init__(self, send_fn, log):
        self._send = send_fn
        self._log = log
        self._next_idx = 1
        self._buf: dict = {}
        self._lock = asyncio.Lock()
        self.total_ref = {"n": 0}

    async def push(self, idx: int, sentence: str, audio: bytes):
        async with self._lock:
            self._buf[idx] = (sentence, audio)
            while self._next_idx in self._buf:
                sent, data = self._buf.pop(self._next_idx)
                try:
                    await self._send({
                        "type": "audio",
                        "index": self._next_idx,
                        "total": self.total_ref["n"],
                        "sentence": sent,
                        "data": data,
                    })
                except Exception as e:
                    self._log.warning(f"⚠️ Reorderer #{self._next_idx}: {e}")
                self._next_idx += 1


class ConnectionHandler:
    def __init__(self, ws: WebSocket, session_id: int, device_id: str):
        self.ws = ws
        self.session_id = session_id
        self.device_id = device_id
        self.log = get_session_logger(session_id, device_id)

        self.dialogue = Dialogue()
        self._init_providers()

        self._captured = {
            "user_wav": None,
            "bot_mp3_parts": [],
        }
        self._pipeline_task: Optional[asyncio.Task] = None

    def _init_providers(self):
        self.asr = ProviderRegistry.create_asr(
            config.asr_provider,
            config={
                "url": config.asr_url,
                "model": config.asr_model,
                "language": config.asr_language,
                "request_timeout": config.asr_request_timeout,
            },
            log=self.log,
        )

        self.llm = ProviderRegistry.create_llm(
            config.llm_provider,
            config={
                "url": config.llm_url,
                "model": config.llm_model,
                "temperature": config.llm_temperature,
                "num_predict": config.llm_num_predict,
                "max_tool_iterations": config.llm_max_tool_iterations,
                "request_timeout": config.llm_request_timeout,
                "think": config.llm_think,        # ✅ Qwen 3.5
            },
            tools_schema=TOOLS_SCHEMA,
            log=self.log,
        )

        self.tts = ProviderRegistry.create_tts(
            config.tts_provider,
            config={
                "voice": config.tts_voice,
                "rate": config.tts_rate,
                "volume": config.tts_volume,
                "request_timeout": config.tts_request_timeout,
                "max_retries": config.tts_max_retries,
                "url": config.tts_vieneu_url,
                "edge_voice": config.tts_edge_voice,
                "piper_model": config.tts_piper_model,
                "piper_binary": config.tts_piper_binary,
            },
            log=self.log,
        )

        self.memory = ProviderRegistry.create_memory(
            config.memory_provider,
            config={
                "max_turns": config.memory_max_turns,
            },
            log=self.log,
        )

    def abort(self):
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            self.log.info("⏹️ Đã gửi cancel tới pipeline")

    async def handle_text(self, user_text: str) -> str:
        self.log.info(f"👤 User: {user_text}")

        normalized = user_text.strip().lower().rstrip(".!?,")

        # ═══ SHORTCUT: GREETING ═══
        GREETINGS = {
            "chào", "chào bạn", "hi", "hello", "xin chào",
            "chào đèn", "hey", "alo",
            "chào buổi sáng", "chào buổi chiều", "chào buổi tối",
        }
        if normalized in GREETINGS:
            return await self._quick_response(user_text, "Chào bạn!")

        # ═══ SHORTCUT: TIME / DATE ═══
        from datetime import datetime as _dt
        import re as _re
        _WD = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        _now = _dt.now()

        # Hỏi thứ
        if _re.search(r"(?i)(hôm\s*nay|nay).{0,10}thứ\s*mấy", normalized) \
                or normalized in {"thứ mấy", "hôm nay thứ", "hôm nay thứ mấy rồi"}:
            return await self._quick_response(
                user_text,
                f"Hôm nay là {_WD[_now.weekday()]}.",
            )

        # Hỏi ngày
        if _re.search(r"(?i)(hôm\s*nay|nay).{0,10}ngày\s*(bao\s*nhiêu|mấy)", normalized) \
                or normalized in {"ngày bao nhiêu", "hôm nay ngày mấy"}:
            return await self._quick_response(
                user_text,
                f"Hôm nay là ngày {_now.day} tháng {_now.month} năm {_now.year}.",
            )

        # Hỏi giờ
        if _re.search(r"(?i)(mấy\s*giờ|bây\s*giờ.{0,5}giờ)", normalized):
            return await self._quick_response(
                user_text,
                f"Bây giờ là {_now.hour} giờ {_now.minute} phút.",
            )

        # ═══ CÒN LẠI → LLM ═══
        self.dialogue.append_user(user_text)
        self._captured["bot_mp3_parts"] = []

        memory_ctx = await self.memory.get_context(str(self.session_id))
        messages = self.dialogue.to_llm_messages(
            memory_str=memory_ctx,
            system_prompt=config.system_prompt,
            max_turns=config.llm_history_keep,
        )

        self._pipeline_task = asyncio.create_task(self._stream_llm_tts(messages))
        try:
            full_response = await self._pipeline_task
        except asyncio.CancelledError:
            self.log.info("⏹️ Pipeline bị cancel")
            raise
        finally:
            self._pipeline_task = None

        # Lọc câu hỏi ngược
        full_response = _clean_response(full_response)
        self.dialogue.append_assistant(full_response)
        await self.memory.save(str(self.session_id), [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_response},
        ])
        return full_response

    async def handle_voice(self, audio_bytes: bytes) -> Optional[str]:
        try:
            wav = await any_to_wav(audio_bytes, sample_rate=config.sample_rate)
            self.log.info(f"🎵 Audio: {len(audio_bytes)} → WAV {len(wav)}b")
        except Exception as e:
            self.log.error(f"❌ Convert audio lỗi: {e}")
            await self._send_error(f"Lỗi audio: {e}")
            return None

        self._captured["user_wav"] = wav
        await self._send_callback({"type": "user_wav", "data": wav})
        await self._send_callback({"type": "status", "text": "Đang nghe..."})

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav)
        elapsed = (time.perf_counter() - t0) * 1000
        self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)

    async def _stream_llm_tts(self, messages: list) -> str:
        full_response = ""
        buffer = ""
        sentence_count = 0
        token_count = 0

        tts_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        stop_marker = object()
        num_workers = max(1, config.tts_workers)
        llm_timeout = max(10.0, float(config.llm_request_timeout))

        reorderer = _AudioReorderer(self._send_callback, self.log)

        await self._send_callback({"type": "tts_start"})

        async def tts_consumer(worker_id: int):
            while True:
                item = await tts_queue.get()
                if item is stop_marker:
                    break
                idx, sentence = item
                try:
                    t0 = time.perf_counter()
                    audio = await asyncio.wait_for(
                        self.tts.synthesize(sentence),
                        timeout=max(10.0, float(config.tts_request_timeout)),
                    )
                    elapsed = (time.perf_counter() - t0) * 1000
                    if audio:
                        await reorderer.push(idx, sentence, audio)
                        self.log.info(
                            f"🔊 W{worker_id} câu #{idx} "
                            f"({len(audio)}b, TTS={elapsed:.0f}ms)"
                        )
                except asyncio.TimeoutError:
                    self.log.warning(f"⏰ TTS câu #{idx} timeout")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"❌ TTS câu #{idx} lỗi: {e}")

        async def run_stream():
            nonlocal full_response, buffer, sentence_count, token_count
            async for item in self.llm.chat_stream(messages):
                t = item.get("type")
                if t == "tool":
                    self.log.info(f"🔧 Tool: {item.get('name')}")
                    await self._send_callback(
                        {"type": "tool", "name": item.get("name")}
                    )
                elif t == "token":
                    token_count += 1
                    tok = item.get("content", "")
                    full_response += tok
                    buffer += tok
                    await self._send_callback({"type": "token", "content": tok})

                    sents, buffer = extract_sentences(buffer)
                    for s in sents:
                        sentence_count += 1
                        reorderer.total_ref["n"] = sentence_count
                        self.log.info(f"[TTS_DBG] Extract #{sentence_count}: {s[:80]!r} (len={len(s)})")
                        await tts_queue.put((sentence_count, s))

            if buffer.strip():
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                self.log.info(f"[TTS_DBG] Câu cuối #{sentence_count}: {buffer[:80]!r} (len={len(buffer)})")
                await tts_queue.put((sentence_count, buffer.strip()))

        consumers = [
            asyncio.create_task(tts_consumer(i + 1))
            for i in range(num_workers)
        ]
        self.log.info(f"🔧 Khởi động {num_workers} TTS workers")

        try:
            await asyncio.wait_for(run_stream(), timeout=llm_timeout)
        except asyncio.TimeoutError:
            self.log.error(f"⏰ LLM stream timeout sau {llm_timeout}s")
            await self._send_callback({
                "type": "error",
                "text": "AI đang quá chậm hoặc không phản hồi. Vui lòng thử lại.",
            })
        except asyncio.CancelledError:
            self.log.info("⏹️ _stream_llm_tts bị cancel")
            raise
        except Exception as e:
            self.log.exception(f"❌ LLM stream lỗi: {e}")
        finally:
            for _ in range(num_workers):
                try:
                    tts_queue.put_nowait(stop_marker)
                except Exception:
                    pass
            try:
                await asyncio.gather(*consumers, return_exceptions=True)
            except asyncio.CancelledError:
                for c in consumers:
                    if not c.done():
                        c.cancel()
            try:
                await self._send_callback({"type": "tts_stop"})
            except Exception:
                pass

        self.log.info(f"✅ Xong: {token_count} tokens, {sentence_count} câu")
        return full_response

    async def _send_callback(self, payload: dict):
        try:
            ptype = payload["type"]
            if ptype == "audio":
                self._captured["bot_mp3_parts"].append(payload["data"])
                meta = {
                    "type": "audio_meta",
                    "index": payload.get("index", 0),
                    "size": len(payload["data"]),
                    "sentence": payload.get("sentence", ""),
                }
                await self.ws.send_json(meta)
                await self.ws.send_bytes(payload["data"])
            elif ptype == "user_wav":
                pass
            else:
                await self.ws.send_json(payload)
        except Exception as e:
            self.log.warning(f"⚠️ send_callback: {e}")

    async def _quick_response(self, user_text: str, response: str) -> str:
        """Trả lời nhanh không qua LLM nhưng CÓ TTS."""
        self.log.info(f"🤖 Quick response: {response!r}")

        self.dialogue.append_user(user_text)
        self.dialogue.append_assistant(response)
        self._captured["bot_mp3_parts"] = []

        try:
            await self._send_callback({"type": "token", "content": response})
        except Exception as e:
            self.log.warning(f"Quick token lỗi: {e}")

        try:
            audio = await asyncio.wait_for(
                self.tts.synthesize(response),
                timeout=10.0,
            )
            if audio:
                await self._send_callback({
                    "type": "audio",
                    "index": 1,
                    "total": 1,
                    "sentence": response,
                    "data": audio,
                })
                self.log.info(f"🔊 Quick TTS: {len(audio)}b")
            else:
                self.log.warning("Quick TTS trả rỗng")
        except asyncio.TimeoutError:
            self.log.warning("Quick TTS timeout 10s")
        except Exception as e:
            self.log.warning(f"Quick TTS lỗi: {e}")

        try:
            await self._send_callback({"type": "end"})
        except Exception:
            pass

        return response

    async def _send_error(self, message: str):
        await self._send_callback({"type": "error", "text": message})

    async def send_end(self):
        await self._send_callback({"type": "end"})

    def get_captured(self, key: str):
        if key == "bot_mp3":
            parts = self._captured.get("bot_mp3_parts") or []
            return b"".join(parts) if parts else None
        return self._captured.get(key)

    def load_history(self, history: list):
        """Load history từ DB vào dialogue."""
        for h in history[-config.llm_history_keep:]:
            self.dialogue.put(Message(role=h["role"], content=h["content"]))

    async def handle_voice_wav(self, wav_bytes: bytes) -> Optional[str]:
        self._captured["user_wav"] = wav_bytes
        await self._send_callback({"type": "user_wav", "data": wav_bytes})
        await self._send_callback({"type": "status", "text": "Đang nghe..."})

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)
```

## `app\core\esp32_connection.py`

```python
"""ESP32ConnectionHandler — convert audio sang Opus."""
import asyncio
import subprocess

from app.core.connection import ConnectionHandler
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio_rate_controller import AudioRateController


class ESP32ConnectionHandler(ConnectionHandler):
    SAMPLE_RATE = 24000

    def __init__(self, ws, session_id: int, device_id: str):
        super().__init__(ws, session_id, device_id)
        self.opus = OpusCodec(sample_rate=self.SAMPLE_RATE, channels=1)
        self.rate_controller = AudioRateController(
            send_fn=self.ws.send_audio,
            frame_duration_ms=60,
            pre_buffer_count=3,   # 3 frame đầu gửi ngay
        )
        self._tts_started = False

    async def _send_callback(self, payload: dict):
        try:
            ptype = payload["type"]

            if ptype == "audio":
                audio_bytes = payload["data"]
                self._captured["bot_mp3_parts"].append(audio_bytes)

                if not self._tts_started:
                    await self.ws.send_json({"type": "tts", "state": "start"})
                    self._tts_started = True

                sentence = payload.get("sentence") or ""
                if sentence:
                    await self.ws.send_json({
                        "type": "tts",
                        "state": "sentence_start",
                        "text": sentence,
                    })

                opus_frames = await self._audio_to_opus_frames(audio_bytes)
                self.log.info(f"🔊 {len(opus_frames)} Opus frames (rate-controlled)")

                # ✅ Reset rate controller cho câu mới
                self.rate_controller.reset()
                for frame in opus_frames:
                    if frame:
                        await self.rate_controller.send(frame)
                self.log.info(f"✅ Sent {len(opus_frames)} frames")

            elif ptype == "stt":
                await self.ws.send_json({
                    "type": "stt",
                    "text": payload.get("text", ""),
                })

            elif ptype == "tts_start":
                pass

            elif ptype == "tts_stop":
                if self._tts_started:
                    await self.ws.send_json({"type": "tts", "state": "stop"})
                    self._tts_started = False
                self.rate_controller.reset()

            elif ptype in ("status", "token", "tool", "user_wav", "end"):
                pass

            else:
                self.log.debug(f"⏭️ Skip type={ptype}")

        except Exception as e:
            self.log.warning(f"⚠️ send_callback: {e}")

    async def _audio_to_opus_frames(self, audio_bytes: bytes) -> list:
        """Audio (MP3/WAV) → PCM 24kHz mono → LIST Opus frames."""
        def _convert():
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-i", "pipe:0",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ac", "1", "-ar", str(self.SAMPLE_RATE),
                    "pipe:1",
                ],
                input=audio_bytes,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="ignore"))
            return proc.stdout

        try:
            pcm = await asyncio.to_thread(_convert)
            return self.opus.encode_frames(pcm)
        except Exception as e:
            self.log.error(f"❌ Audio→Opus frames lỗi: {e}")
            return []
```

## `app\core\logger.py`

```python
"""Smart Logging — module string + per-session file."""
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict
from loguru import logger

from app.config import config


LOG_DIR = Path(config.log_dir)
SESSION_LOG_DIR = LOG_DIR / "sessions"

LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _abbrev(name: str) -> str:
    if not name:
        return "00"
    if "_" in name:
        parts = name.split("_")
        return (parts[-1][:2] if parts[-1] else "00").lower()
    return name[:2].lower()


def build_module_string() -> str:
    return (
        _abbrev("silero")
        + _abbrev(config.asr_provider)
        + _abbrev(config.llm_provider)
        + _abbrev(config.tts_provider)
        + _abbrev(config.memory_provider)
        + _abbrev("function_call")
        + "00"
    )


class SessionFileSink:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._files: Dict[str, object] = {}
        self._lock = threading.Lock()

    def _get_file(self, session_id):
        sid = str(session_id)
        if sid not in self._files:
            path = self.base_dir / f"{sid}.log"
            self._files[sid] = open(path, "a", encoding="utf-8")
        return self._files[sid]

    def __call__(self, message):
        try:
            sid = message.record["extra"].get("session_id")
            if sid in (None, "-", 0, "0"):
                return
            with self._lock:
                f = self._get_file(sid)
                f.write(message)
                f.flush()
        except Exception:
            pass

    def close_all(self):
        with self._lock:
            for f in self._files.values():
                try:
                    f.close()
                except Exception:
                    pass
            self._files.clear()


_session_sink: SessionFileSink = None
_logger_initialized = False
_MODULE_STRING = "00000000000000"

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green>|"
    "[<light-blue>{extra[module_string]}</light-blue>]|"
    "[<cyan>{extra[session_short]}</cyan>]|"
    "<level>{level: <7}</level>|"
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} - "
    "v{extra[version]}_{extra[module_string]} - "
    "{name} - {level} - "
    "[session={extra[session_id]}] - "
    "[device={extra[device_id]}] - "
    "{message}"
)


def setup_logging(level: str = None) -> None:
    global _logger_initialized, _MODULE_STRING, _session_sink

    if _logger_initialized:
        return

    _MODULE_STRING = build_module_string()
    level = level or config.log_level

    logger.configure(extra={
        "session_id": "-",
        "session_short": "------",
        "device_id": "-",
        "module_string": _MODULE_STRING,
        "version": config.version,
    })

    logger.remove()

    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    logger.add(
        LOG_DIR / "app.log",
        format=FILE_FORMAT,
        level="DEBUG",
        rotation=f"{config.log_main_rotation_mb} MB",
        retention=config.log_retention_days,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    logger.add(
        LOG_DIR / "errors.log",
        format=FILE_FORMAT,
        level="WARNING",
        rotation=f"{config.log_error_rotation_mb} MB",
        retention=config.log_retention_days * 2,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    _session_sink = SessionFileSink(SESSION_LOG_DIR)
    logger.add(
        _session_sink,
        format=FILE_FORMAT,
        level="DEBUG",
        enqueue=False,
    )

    _logger_initialized = True
    logger.info(
        f"📝 Logging khởi động | level={level} | "
        f"modules={_MODULE_STRING} | dir={LOG_DIR.resolve()}"
    )


def shutdown_logging():
    global _session_sink
    if _session_sink:
        _session_sink.close_all()


def get_session_logger(session_id, device_id: str = "-"):
    sid = session_id if session_id is not None else "-"
    short = f"#{str(sid)[:6]:>6}" if sid != "-" else "------"
    return logger.bind(session_id=sid, session_short=short, device_id=device_id)


def list_session_logs() -> list:
    if not SESSION_LOG_DIR.exists():
        return []
    files = []
    for p in sorted(
        SESSION_LOG_DIR.glob("*.log"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        stat = p.stat()
        files.append({
            "session_id": p.stem,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                "%H:%M %d/%m/%Y"
            ),
        })
    return files


def read_session_log(session_id: str, tail: int = 500) -> str:
    path = SESSION_LOG_DIR / f"{session_id}.log"
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-tail:])


def cleanup_old_logs(days: int = None) -> int:
    from time import time
    days = days or config.log_retention_days
    cutoff = time() - days * 86400
    deleted = 0
    for p in SESSION_LOG_DIR.glob("*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                deleted += 1
        except Exception:
            pass
    return deleted
```

## `app\core\mqtt_server.py`

```python
"""MQTT Broker adapter — bridge MQTT messages ↔ ConnectionHandler.

Windows note:
    Uvicorn trên Windows dùng ProactorEventLoop.
    aiomqtt/paho cần add_reader → NotImplementedError trên Proactor.
    → Chạy MQTT client trong thread riêng với SelectorEventLoop.
    → Forward messages sang main loop qua run_coroutine_threadsafe.
"""
import asyncio
import json
import sys
import threading
from typing import Optional, Dict
import aiomqtt
from loguru import logger
from app.config import config
from app.core.utils.udp_crypto import UdpCrypto, generate_key_nonce

class MqttBroker:
    """
    MQTT client chạy trong thread riêng với SelectorEventLoop.
    """

    def __init__(self):
        self.host = config.mqtt_broker_host
        self.port = config.mqtt_broker_port
        self.username = config.mqtt_username
        self.password = config.mqtt_password

        self._client: Optional[aiomqtt.Client] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._mqtt_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._on_message = None
        self._ready = threading.Event()

    def set_message_handler(self, handler):
        self._on_message = handler

    async def start(self):
        if not config.mqtt_enabled:
            logger.info("📡 MQTT disabled")
            return

        logger.info(f"📡 MQTT client → {self.host}:{self.port}")

        # Lưu main loop (uvicorn loop) — chạy trong main thread
        self._main_loop = asyncio.get_running_loop()

        # Khởi động MQTT thread
        self._thread = threading.Thread(
            target=self._run_thread,
            daemon=True,
            name="mqtt-broker",
        )
        self._thread.start()

        # Chờ MQTT thread ready (tối đa 5s)
        ready = await self._main_loop.run_in_executor(
            None, self._ready.wait, 5.0
        )
        if not ready:
            logger.warning("⚠️ MQTT thread không ready sau 5s")
        else:
            logger.info("📡 MQTT broker thread ready")

    def _run_thread(self):
        """Entry point của MQTT thread."""
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(
                asyncio.WindowsSelectorEventLoopPolicy()
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._mqtt_loop = loop

        self._ready.set()

        try:
            loop.run_until_complete(self._run_forever())
        except Exception as e:
            logger.exception(f"❌ MQTT thread crash: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._mqtt_loop = None

    async def _run_forever(self):
        """Loop chính của MQTT client — chạy trong MQTT thread."""
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ MQTT lỗi: {e} — reconnect 5s")
                await asyncio.sleep(5)

    # ============ SAFE HANDLER — bắt exception ============
    async def _safe_handler(self, msg):
        """Wrapper có log lỗi — tránh exception bị nuốt vào Future."""
        try:
            await self._on_message(msg)
        except Exception as e:
            logger.exception(f"❌ MQTT handler crash: {e}")

    async def _connect_and_listen(self):
        """Kết nối broker và lắng nghe messages."""
        kwargs = {"hostname": self.host, "port": self.port}
        if self.username:
            kwargs["username"] = self.username
        if self.password:
            kwargs["password"] = self.password

        async with aiomqtt.Client(**kwargs) as client:
            self._client = client
            logger.info("✅ MQTT connected")
            await client.subscribe("xiaozhi/+/up")
            logger.info("📡 Subscribed: xiaozhi/+/up")

            async for msg in client.messages:
                if not self._on_message or not self._main_loop:
                    continue

                # ✅ Forward sang main loop + log exception nếu có
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._safe_handler(msg),
                        self._main_loop,
                    )
                    future.add_done_callback(self._on_future_done)
                except Exception as e:
                    logger.exception(f"❌ MQTT forward lỗi: {e}")

    @staticmethod
    def _on_future_done(fut):
        """Log exception từ coroutine chạy trên main loop."""
        try:
            fut.result()
        except Exception as e:
            logger.exception(f"❌ MQTT future exception: {e}")

    async def publish(self, topic: str, payload: str):
        """Publish — tự động forward sang MQTT thread nếu cần."""
        if not self._client or not self._mqtt_loop:
            logger.warning("⚠️ MQTT chưa connect")
            return

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        try:
            if current is self._mqtt_loop:
                # Đang trong MQTT thread → publish trực tiếp
                await self._client.publish(topic, payload)
            else:
                # Đang ở main loop → forward sang MQTT thread
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.publish(topic, payload),
                    self._mqtt_loop,
                )
                await asyncio.wrap_future(fut)
        except Exception as e:
            logger.warning(f"⚠️ MQTT publish lỗi: {e}")

    async def stop(self):
        if self._thread and self._thread.is_alive():
            logger.info("🛑 Stopping MQTT broker...")
            if self._mqtt_loop and self._mqtt_loop.is_running():
                self._mqtt_loop.call_soon_threadsafe(self._mqtt_loop.stop)
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._thread.join, 3.0
                )
            except Exception:
                pass

class MqttConnectionManager:
    def __init__(self):
        self.broker = MqttBroker()
        self.sessions: Dict[str, dict] = {}
        self.nonce_to_device: Dict[str, str] = {}

    async def start(self):
        if not config.mqtt_enabled:
            return
        self.broker.set_message_handler(self._on_mqtt_message)
        await self.broker.start()
        from app.core.udp_server import get_udp_server
        udp = get_udp_server()
        udp.set_audio_handler(self._on_udp_audio)
        await udp.start()

    async def stop(self):
        await self.broker.stop()
        from app.core.udp_server import get_udp_server
        await get_udp_server().stop()

    async def _on_mqtt_message(self, msg):
        """Entry point — được gọi từ MQTT thread qua forward."""
        try:
            topic = str(msg.topic)
            parts = topic.split("/")
            if len(parts) < 3:
                logger.warning(f"⚠️ Topic sai format: {topic}")
                return
            device_id = parts[1]

            try:
                data = json.loads(msg.payload.decode("utf-8"))
            except Exception as e:
                logger.warning(f"⚠️ Payload không phải JSON: {e}")
                return

            msg_type = data.get("type")
            logger.debug(f"📨 MQTT [{device_id}] type={msg_type}")

            if msg_type == "hello":
                await self._handle_hello(device_id, data)
            elif msg_type == "sensor_data":
                from app.core.providers.tools import sensor_state
                sensor_state.update_bulk({
                    "temperature": data.get("temperature"),
                    "humidity": data.get("humidity"),
                    "air_quality_ppm": data.get("air_quality_ppm"),
                    "light_lux": data.get("light_lux"),
                    "presence": data.get("presence"),
                })
                logger.info(f"📊 Sensor updated từ {device_id}: {data}")
            elif msg_type == "mcp":
                payload = data.get("payload", {})
                logger.info(f"📥 MCP reply từ {device_id}: {str(payload)[:200]}")
                s = self.sessions.get(device_id)
                if s and "_mcp_future" in s:
                    fut = s["_mcp_future"]
                    if not fut.done():
                        fut.set_result(payload)
            elif msg_type == "mcp_reply":
                logger.info(
                    f"📥 MCP reply (legacy) từ {device_id}: "
                    f"{data.get('method')} → {data.get('result')}"
                )
                s = self.sessions.get(device_id)
                if s and "_mcp_future" in s:
                    fut = s["_mcp_future"]
                    if not fut.done():
                        fut.set_result({"result": data.get("result")})

            elif device_id in self.sessions:
                await self._handle_control(device_id, data)
            else:
                logger.debug(f"📨 Bỏ qua (chưa hello): {msg_type}")
        except Exception as e:
            logger.exception(f"❌ _on_mqtt_message crash: {e}")
            raise

    async def _handle_hello(self, device_id: str, data: dict):
        """Xử lý hello — có log từng bước để debug."""
        from app.core.logger import get_session_logger

        log = get_session_logger(None, device_id)
        log.info(f"🔌 MQTT hello từ {device_id}")

        try:
            log.debug("[1/6] Import các module cần thiết")
            from app.core.esp32_connection import ESP32ConnectionHandler
            from app.core.protocols import MqttTransport
            from app.core.utils.opus_codec import OpusCodec
            from app.core.providers.vad.energy import EnergyVAD
            from app.core.providers.vad.silero import SileroVAD
            
            from app.database import AsyncSessionLocal
            from app.services import chat as chat_service
            from app.config import config as _cfg
        except Exception as e:
            log.exception(f"❌ Import fail: {e}")
            raise

        try:
            log.debug("[2/6] Tạo session trong DB")
            async with AsyncSessionLocal() as db:
                await chat_service.get_or_create_device(db, device_id, "esp32")
                session, is_new = await chat_service.resume_or_create_session(
                    db, device_id, None,
                )
                session_id = session.id
        except Exception as e:
            log.exception(f"❌ Tạo session fail: {e}")
            raise

        log = get_session_logger(session_id, device_id)
        log.debug(f"[3/6] Session #{session_id} (new={is_new})")

        try:
            log.debug("[4/6] Sinh AES key/nonce + tạo transport + handler")
            aes_key_hex, aes_nonce_hex = generate_key_nonce()
            crypto = UdpCrypto(aes_key_hex, aes_nonce_hex)
            log.info(f"🔑 Sinh key/nonce | key={aes_key_hex[:8]}... nonce={aes_nonce_hex[:8]}...")

            transport = MqttTransport(
                device_id=device_id,
                broker=self.broker,
                crypto=crypto,
            )
            handler = ESP32ConnectionHandler(transport, session_id, device_id)
        except Exception as e:
            log.exception(f"❌ Tạo handler fail: {e}")
            raise

        try:
            log.debug("[5/6] Tạo VAD + Opus codec")
            vad_cfg = _cfg.vad_config
            vad_type = _cfg.vad_provider  # "energy" hoặc "silero"

            if vad_type == "silero":
                model_dir = vad_cfg.get("model_dir", "models/snakers4_silero-vad")
                vad = SileroVAD(
                    model_path=f"{model_dir}/silero_vad.onnx",
                    sample_rate=16000,
                    threshold=vad_cfg.get("threshold", 0.5),
                    threshold_low=vad_cfg.get("threshold_low", 0.2),
                    silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
                    min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
                )
                log.info(f"🎤 Dùng SileroVAD | threshold={vad.threshold}")
            else:
                vad = EnergyVAD(
                    sample_rate=16000,
                    frame_duration_ms=60,
                    silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
                    min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
                    energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
                    initial_threshold=vad_cfg.get("initial_threshold", 500.0),
                    hangover_ms=vad_cfg.get("hangover_ms", 200),
                    pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
                    post_speech_ms=vad_cfg.get("post_speech_ms", 300),
                )
                log.info(f"🎤 Dùng EnergyVAD | threshold={vad.threshold:.0f}")
            opus = OpusCodec(sample_rate=16000, channels=1)
        except Exception as e:
            log.exception(f"❌ Tạo VAD/Opus fail: {e}")
            raise

        self.sessions[device_id] = {
            "session_id": session_id,
            "handler": handler,
            "transport": transport,
            "vad": vad,
            "opus": opus,
            "crypto": crypto,
            "aes_nonce_hex": aes_nonce_hex,
            "udp_addr": None,
            "log": log,
            "process_task": None,
            "listen_mode": "auto",
        }
        # ✅ Đăng ký nonce -> device_id để định tuyến UDP
        self.nonce_to_device[aes_nonce_hex] = device_id

        try:
            log.debug("[6/6] Gửi hello response")
            await transport.send_json({
                "type": "hello",
                "version": 3,
                "session_id": str(session_id),
                "transport": "udp",
                "udp": {
                    "server": _cfg.udp_endpoint,
                    "port": _cfg.udp_port,
                    "key": aes_key_hex,
                    "nonce": aes_nonce_hex,
                },
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            })
        except Exception as e:
            log.exception(f"❌ Gửi hello response fail: {e}")
            raise

        log.info(f"✅ MQTT session #{session_id} ready")

    async def _handle_control(self, device_id: str, data: dict):
        s = self.sessions.get(device_id)
        if not s:
            return
        log = s["log"]
        msg_type = data.get("type")

        if msg_type == "listen":
            mode = (data.get("mode") or "auto").lower()
            state = (data.get("state") or "").lower()
            s["listen_mode"] = mode

            if state == "start":
                log.info(f"🎤 Listen START | mode={mode}")
                s["vad"].reset()
                s["_manual_pcm"] = []
                s["_listening"] = True

            elif state == "stop":
                log.info(f"🎤 Listen STOP | mode={mode}")
                s["_listening"] = False

                if mode == "manual":
                    pcm_chunks = s.get("_manual_pcm", [])
                    if pcm_chunks:
                        pcm = b"".join(pcm_chunks)
                        log.info(f"📦 Manual: {len(pcm)}b PCM → ASR")
                        task = s.get("process_task")
                        if task is None or task.done():
                            s["process_task"] = asyncio.create_task(
                                self._process_pcm(s, pcm)
                            )
                    s["_manual_pcm"] = []

            elif state == "detect":
                log.info(f"🎤 Listen DETECT | mode={mode}")
                s["vad"].reset()

            else:
                log.info(f"🎤 Listen mode={mode} (no state)")
                s["vad"].reset()

        elif msg_type == "abort":
            task = s.get("process_task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except Exception:
                    pass
                s["process_task"] = None
            s["handler"].abort()
            s["vad"].reset()
            s["_manual_pcm"] = []
            s["_listening"] = False
            log.info("⏹️ Abort")

        elif msg_type == "goodbye":
            await self._close_session(device_id)

    async def _on_udp_audio(self, data: bytes, addr: tuple):
        # Packet: [16b header][encrypted] — KHÔNG có nonce
        if len(data) < 16:
            logger.warning(f"⚠️ UDP packet quá ngắn: {len(data)}b")
            return

        # 1. Tìm session đã bind với addr này
        for device_id, s in self.sessions.items():
            if s["udp_addr"] == addr:
                await self._process_udp(device_id, s, data)
                return

        # 2. Chưa bind → bind vào session đang chờ
        for device_id, s in self.sessions.items():
            if s["udp_addr"] is None:
                s["udp_addr"] = addr
                if hasattr(s["transport"], "udp_addr"):
                    s["transport"].udp_addr = addr
                s["log"].info(f"📡 UDP bound: {addr}")
                await self._process_udp(device_id, s, data)
                return

        logger.debug(f"⚠️ UDP từ addr lạ: {addr}")

    async def _process_udp(self, device_id: str, s: dict, packet: bytes):
        log = s["log"]

        err_count = s.get("udp_err_count", 0)
        if len(packet) < 16:
            return

        import struct

        # ✅ 16 byte đầu tiên CHÍNH LÀ NONCE
        packet_nonce = packet[:16]
        encrypted = packet[16:]

        if not encrypted:
            return

        # Parse metadata để debug
        type_ = packet_nonce[0]
        seq = struct.unpack(">I", packet_nonce[12:16])[0]

        # ✅ Giải mã với nonce ĐẦY ĐỦ từ gói
        try:
            opus_frame = s["crypto"].decrypt_with_packet_nonce(encrypted, packet_nonce)
        except Exception as e:
            if err_count < 3: log.warning(f"⚠️ AES decrypt: {e}")
            s["udp_err_count"] = err_count + 1
            return

        if not opus_frame:
            return

        # ✅ Bước 2: Opus decode -> PCM
        try:
            pcm = s["opus"].decode(opus_frame)
        except Exception as e:
            log.warning(f"⚠️ Opus decode: {e}")
            return

        mode = s.get("listen_mode", "auto")

        if mode == "manual":
            # Manual: tích lũy PCM chờ state=stop
            s.setdefault("_manual_pcm", []).append(pcm)
            if len(s["_manual_pcm"]) > 500:
                s["_manual_pcm"] = s["_manual_pcm"][-500:]
            return

        # Auto mode: VAD detect end-of-speech
        is_end = s["vad"].push(pcm)
        if is_end:
            pcm_data = s["vad"].get_audio()
            s["vad"].reset()
            task = s.get("process_task")
            if pcm_data and (task is None or task.done()):
                s["process_task"] = asyncio.create_task(
                    self._process_pcm(s, pcm_data)
                )

    async def _process_pcm(self, s: dict, pcm: bytes):
        import io, wave
        log = s["log"]
        handler = s["handler"]
        session_id = s["session_id"]

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm)
        wav = buf.getvalue()

        try:
            user_text = await handler.handle_voice_wav(wav)
            log.info(f"✅ Pipeline | user='{user_text}'")

            from app.database import AsyncSessionLocal
            from app.services import chat as chat_service

            if user_text:
                async with AsyncSessionLocal() as db:
                    await chat_service.save_message(
                        db, session_id, "user", user_text,
                        audio_bytes=handler.get_captured("user_wav"),
                        audio_ext="wav",
                    )
                    bot_msg = handler.dialogue.last_assistant()
                    if bot_msg and bot_msg.content:
                        await chat_service.save_message(
                            db, session_id, "assistant", bot_msg.content,
                            audio_bytes=handler.get_captured("bot_mp3"),
                            audio_ext="mp3",
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"❌ Pipeline: {e}")

    async def _close_session(self, device_id: str):
        s = self.sessions.pop(device_id, None)
        if not s:
            return

        # ✅ Xóa ánh xạ nonce -> device_id
        nonce = s.get("aes_nonce_hex")
        if nonce:
            self.nonce_to_device.pop(nonce, None)

        task = s.get("process_task")
        if task and not task.done():
            task.cancel()

        from app.database import AsyncSessionLocal
        from app.services import chat as chat_service

        try:
            async with AsyncSessionLocal() as db:
                await chat_service.close_session(db, s["session_id"])
        except Exception:
            pass

_manager: Optional[MqttConnectionManager] = None

def get_mqtt_manager() -> MqttConnectionManager:
    global _manager
    if _manager is None:
        _manager = MqttConnectionManager()
    return _manager
```

## `app\core\api\ota_handler.py`

```python
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
```

## `app\core\protocols\base.py`

```python
"""Transport abstraction — WebSocket vs MQTT+UDP."""
from abc import ABC, abstractmethod
import asyncio


class Transport(ABC):
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    async def send_json(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_audio(self, audio: bytes) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class WebSocketTransport(Transport):
    """WS transport có timeout — tránh treo khi ESP32 không đọc."""

    SEND_TIMEOUT = 10.0

    def __init__(self, ws):
        self.ws = ws
        self._connected = True

    @property
    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            return self.ws.client_state.name == "CONNECTED"
        except Exception:
            return False

    async def send_json(self, payload: dict) -> None:
        if not self._connected:
            raise ConnectionError("WS disconnected")
        try:
            await asyncio.wait_for(
                self.ws.send_json(payload),
                timeout=self.SEND_TIMEOUT,
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            self._connected = False
            raise ConnectionError(f"WS send_json dead: {e}")

    async def send_audio(self, audio: bytes) -> None:
        if not self._connected:
            raise ConnectionError("WS disconnected")
        try:
            await asyncio.wait_for(
                self.ws.send_bytes(audio),
                timeout=self.SEND_TIMEOUT,
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            self._connected = False
            raise ConnectionError(f"WS send_bytes dead: {e}")

    async def close(self) -> None:
        self._connected = False
        try:
            await asyncio.wait_for(self.ws.close(), timeout=3.0)
        except Exception:
            pass


class MqttTransport(Transport):
    def __init__(self, device_id: str, broker, crypto=None, udp_addr=None):
        self.device_id = device_id
        self.broker = broker
        self.crypto = crypto
        self.udp_addr = udp_addr
        self._seq = 1
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_json(self, payload: dict) -> None:
        if not self._connected:
            return
        import json
        topic = f"xiaozhi/{self.device_id}/down"
        await asyncio.wait_for(
            self.broker.publish(topic, json.dumps(payload)),
            timeout=10.0,
        )

    async def send_audio(self, opus_bytes: bytes) -> None:
        if not self._connected or not self.udp_addr or not self.crypto:
            return
        import time

        packet_nonce = bytearray(self.crypto.nonce)
        payload_len = len(opus_bytes)
        ts = int(time.time() * 1000) & 0xFFFFFFFF
        seq = self._seq & 0xFFFFFFFF

        packet_nonce[0] = 0x01
        packet_nonce[1] = 0x00
        packet_nonce[2:4] = payload_len.to_bytes(2, "big")
        packet_nonce[4:8] = (0).to_bytes(4, "big")
        packet_nonce[8:12] = ts.to_bytes(4, "big")
        packet_nonce[12:16] = seq.to_bytes(4, "big")

        encrypted = self.crypto.encrypt_with_packet_nonce(
            opus_bytes, bytes(packet_nonce)
        )
        packet = bytes(packet_nonce) + encrypted

        from app.core.udp_server import get_udp_server
        await asyncio.wait_for(
            get_udp_server().send_audio(self.udp_addr, packet),
            timeout=5.0,
        )
        self._seq += 1

    async def close(self) -> None:
        self._connected = False
```

## `app\core\protocols\__init__.py`

```python
from app.core.protocols.base import Transport, WebSocketTransport, MqttTransport
__all__ = ["Transport", "WebSocketTransport", "MqttTransport"]
```

## `app\core\providers\base.py`

```python
"""Base classes cho providers."""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, List
from loguru import logger


class ASRProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        ...


class LLMProviderBase(ABC):
    def __init__(self, config: dict, tools_schema: list = None, log=None):
        self.config = config
        self.tools_schema = tools_schema or []
        self.log = log or logger

    @abstractmethod
    async def chat_stream(self, messages, tools=None) -> AsyncGenerator[dict, None]:
        ...


class TTSProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def synthesize(self, text: str, **kwargs) -> bytes:
        ...


class MemoryProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        ...

    @abstractmethod
    async def save(self, session_id: str, messages: List[dict]) -> None:
        ...


class ProviderRegistry:
    _ASR = {}
    _LLM = {}
    _TTS = {}
    _MEMORY = {}

    @classmethod
    def register_asr(cls, name, provider_cls):
        cls._ASR[name] = provider_cls

    @classmethod
    def register_llm(cls, name, provider_cls):
        cls._LLM[name] = provider_cls

    @classmethod
    def register_tts(cls, name, provider_cls):
        cls._TTS[name] = provider_cls

    @classmethod
    def register_memory(cls, name, provider_cls):
        cls._MEMORY[name] = provider_cls

    @classmethod
    def create_asr(cls, name, **kwargs):
        p = cls._ASR.get(name)
        if not p:
            raise ValueError(f"ASR provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_llm(cls, name, **kwargs):
        p = cls._LLM.get(name)
        if not p:
            raise ValueError(f"LLM provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_tts(cls, name, **kwargs):
        p = cls._TTS.get(name)
        if not p:
            raise ValueError(f"TTS provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_memory(cls, name, **kwargs):
        p = cls._MEMORY.get(name)
        if not p:
            raise ValueError(f"Memory provider '{name}' không tồn tại")
        return p(**kwargs)
```

## `app\core\providers\__init__.py`

```python
from app.core.providers.base import ProviderRegistry
from app.core.providers.asr import phowhisper  # noqa
from app.core.providers.llm import ollama      # noqa
from app.core.providers.tts import edge, piper , vieneu  # noqa
from app.core.providers.memory import local, none  # noqa

__all__ = ["ProviderRegistry"]
```

## `app\core\providers\asr\phowhisper.py`

```python
"""PhoWhisper ASR provider."""
import httpx
from app.core.providers.base import ASRProviderBase, ProviderRegistry


class PhoWhisperProvider(ASRProviderBase):
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        language = language or self.config.get("language", "vi")
        url = self.config.get("url")
        model = self.config.get("model", "phowhisper")
        timeout = self.config.get("request_timeout", 60.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
                data = {"language": language, "model": model}
                r = await client.post(url, files=files, data=data)
                r.raise_for_status()
                text = r.json().get("text", "").strip()
                self.log.info(f"📝 ASR: {text}")
                return text
        except httpx.ConnectError:
            self.log.error("❌ Không kết nối được ASR server")
            return ""
        except httpx.TimeoutException:
            self.log.error("❌ ASR timeout")
            return ""
        except Exception as e:
            self.log.error(f"❌ ASR lỗi: {e}")
            return ""


ProviderRegistry.register_asr("phowhisper", PhoWhisperProvider)
```

## `app\core\providers\llm\ollama.py`

```python
"""Ollama LLM provider — stream thật, hỗ trợ Qwen 3.5 thinking."""
import json
import httpx
from typing import AsyncGenerator
from app.core.providers.base import LLMProviderBase, ProviderRegistry


class OllamaProvider(LLMProviderBase):
    async def chat_stream(self, messages, tools=None) -> AsyncGenerator[dict, None]:
        url = self.config.get("url")
        model = self.config.get("model")
        timeout = self.config.get("request_timeout", 120.0)
        max_iter = self.config.get("max_tool_iterations", 5)
        temperature = self.config.get("temperature", 0.7)
        num_predict = self.config.get("num_predict", 512)
        # ✅ Qwen 3.5 thinking mode — mặc định tắt
        think = self.config.get("think", False)

        tools_to_use = tools if tools is not None else self.tools_schema

        for iteration in range(max_iter):
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "think": think,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
            }
            # Chỉ gửi tools khi có
            if tools_to_use:
                payload["tools"] = tools_to_use

            content_buffer = ""
            tool_calls_buffer = []

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, json=payload) as r:
                        r.raise_for_status()
                        async for line in r.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            msg = chunk.get("message", {})

                            # ✅ Bỏ qua thinking content (Qwen 3.5)
                            tok = msg.get("content")
                            if tok:
                                content_buffer += tok
                                yield {"type": "token", "content": tok}

                            # ✅ Nếu có thinking field riêng, cũng bỏ qua
                            # (không đưa vào buffer để không TTS thinking)

                            for tc in (msg.get("tool_calls") or []):
                                tool_calls_buffer.append(tc)

                            if chunk.get("done"):
                                break

            except httpx.ConnectError:
                self.log.error("❌ Không kết nối được Ollama")
                yield {"type": "token", "content": "Xin lỗi, không kết nối được AI."}
                return
            except httpx.TimeoutException:
                self.log.error("❌ Ollama timeout")
                yield {"type": "token", "content": "Xin lỗi, AI phản hồi quá chậm."}
                return
            except Exception as e:
                self.log.exception(f"❌ LLM lỗi: {e}")
                yield {"type": "token", "content": "Xin lỗi, có lỗi xảy ra."}
                return

            if not tool_calls_buffer:
                return

            # Dedup tool calls theo tên
            seen = {}
            for tc in tool_calls_buffer:
                name = tc.get("function", {}).get("name")
                if name and name not in seen:
                    seen[name] = tc
            tool_calls = list(seen.values())

            self.log.info(f"🔧 LLM gọi {len(tool_calls)} tool(s) (iter {iteration + 1})")
            messages.append({
                "role": "assistant",
                "content": content_buffer,
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = call["function"]["arguments"]
                # ✅ Sinh ID nếu Ollama không cấp
                call_id = call.get("id") or f"call_{fn_name}_{iteration}"

                yield {"type": "tool", "name": fn_name, "args": fn_args}

                result = await self._execute_tool(fn_name, fn_args)
                self.log.info(f"   ← {fn_name}: {result[:100]}")
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": call_id,
                })

        self.log.warning(f"⚠️ Vượt quá {max_iter} iterations")
        yield {"type": "token", "content": "Xin lỗi, tôi không xử lý được yêu cầu."}

    async def _execute_tool(self, name: str, arguments) -> str:
        from app.core.providers.tools.registry import execute_tool
        return await execute_tool(name, arguments)


ProviderRegistry.register_llm("ollama", OllamaProvider)
```

## `app\core\providers\memory\local.py`

```python
"""Local memory provider — RAM."""
from typing import Dict, List, Optional
from collections import deque
from app.core.providers.base import MemoryProviderBase, ProviderRegistry


class LocalMemoryProvider(MemoryProviderBase):
    def __init__(self, config: dict, log=None):
        super().__init__(config, log)
        self._store: Dict[str, deque] = {}
        self.max_turns = config.get("max_turns", 20)

    def _get_deque(self, session_id: str) -> deque:
        if session_id not in self._store:
            self._store[session_id] = deque(maxlen=self.max_turns)
        return self._store[session_id]

    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        dq = self._store.get(session_id)
        if not dq:
            return None
        lines = [f"- {item}" for item in dq if item]
        return "\n".join(lines) if lines else None

    async def save(self, session_id: str, messages: List[dict]) -> None:
        dq = self._get_deque(session_id)
        for msg in messages:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if not content or role == "system":
                continue
            if role in ("user", "assistant"):
                dq.append(f"[{role}] {content[:120]}")

    def clear(self, session_id: str):
        self._store.pop(session_id, None)


ProviderRegistry.register_memory("local", LocalMemoryProvider)
```

## `app\core\providers\tools\impl.py`

```python
"""Tools — subject routing (SearXNG + Tavily + Wikipedia).

Router logic:
    realtime/product/news/howto  → Tavily → SearXNG → ddgs
    person/concept/place         → Wikipedia → Tavily → SearXNG
    general                      → SearXNG → Tavily → ddgs
"""
import asyncio
import html as html_mod
import re
from datetime import datetime, date as date_cls, timedelta
from typing import Any

import httpx
from loguru import logger

from app.config import config


# =====================================================
# CONSTANTS
# =====================================================

WMO_CODES = {
    0: "Trời quang", 1: "Ít mây", 2: "Có mây", 3: "Nhiều mây",
    45: "Sương mù", 48: "Sương mù đóng băng",
    51: "Mưa phùn nhẹ", 53: "Mưa phùn", 55: "Mưa phùn nặng",
    61: "Mưa nhẹ", 63: "Mưa", 65: "Mưa to",
    71: "Tuyết nhẹ", 73: "Tuyết", 75: "Tuyết to",
    80: "Mưa rào nhẹ", 81: "Mưa rào", 82: "Mưa rào to",
    95: "Giông", 96: "Giông có mưa đá", 99: "Giông mưa đá to",
}

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

DATE_ALIASES = {
    "hôm nay": 0, "ngày mai": 1, "mai": 1,
    "ngày kia": 2, "mốt": 2,
    "hôm qua": -1, "hôm kia": -2,
}


# =====================================================
# SUBJECT CLASSIFIER
# =====================================================

PERSON_PATTERNS = re.compile(
    r"\b(là ai|tiểu sử|sinh năm|mất năm|nhà văn|nhà thơ|ca sĩ|"
    r"diễn viên|tổng thống|chủ tịch|vua|danh nhân|anh hùng|"
    r"nghệ sĩ|nhạc sĩ|họa sĩ|giáo sư|tiến sĩ)\b", re.IGNORECASE)

CONCEPT_PATTERNS = re.compile(
    r"\b(là gì|định nghĩa|khái niệm|nghĩa là|thuật ngữ|"
    r"nguyên lý|định lý|công thức)\b", re.IGNORECASE)

PLACE_PATTERNS = re.compile(
    r"\b(thủ đô|thành phố|tỉnh|quốc gia|đất nước|"
    r"châu lục|đại dương|con sông|ngọn núi|ở đâu|nằm ở)\b", re.IGNORECASE)

REALTIME_PATTERNS = re.compile(
    r"\b(tỷ số|tỉ số|livescore|kết quả bóng|kết quả trận|"
    r"giá vàng|giá đô|tỷ giá|usd|eur|bitcoin|btc|"
    r"chứng khoán|vn-index|cổ phiếu|lãi suất|"
    r"xổ số|xskt|lô tô|nhiệt độ|bao nhiêu độ|có mưa không|"
    r"dự báo thời tiết|giá xăng|giá điện|giá cả|hôm nay bao nhiêu|"
    r"bảng xếp hạng|lịch thi đấu)\b", re.IGNORECASE)

NEWS_PATTERNS = re.compile(
    r"\b(tin tức|thời sự|sự kiện|mới nhất|hôm nay có gì|"
    r"bản tin|thông tin mới|diễn biến|tình hình)\b", re.IGNORECASE)

HOWTO_PATTERNS = re.compile(
    r"\b(cách|làm sao|hướng dẫn|thủ thuật|mẹo|"
    r"cài đặt|setup|tutorial|chỉ cách)\b", re.IGNORECASE)

PRODUCT_PATTERNS = re.compile(
    r"\b(giá|review|đánh giá|mua ở đâu|so sánh|"
    r"iphone|samsung|xiaomi|vinfast|honda|toyota|"
    r"laptop|điện thoại|tai nghe)\b", re.IGNORECASE)


def _classify_subject(query: str) -> str:
    q = query.strip()
    if REALTIME_PATTERNS.search(q):
        return "realtime"
    if PRODUCT_PATTERNS.search(q):
        return "product"
    if PERSON_PATTERNS.search(q):
        return "person"
    if PLACE_PATTERNS.search(q):
        return "place"
    if CONCEPT_PATTERNS.search(q):
        return "concept"
    if NEWS_PATTERNS.search(q):
        return "news"
    if HOWTO_PATTERNS.search(q):
        return "howto"
    return "general"


# =====================================================
# HTTP CLIENT — REUSE (tránh connection leak)
# =====================================================

_http_client: httpx.AsyncClient | None = None


async def _http() -> httpx.AsyncClient:
    """Singleton httpx client — reuse connection pool."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        )
    return _http_client


async def close_http() -> None:
    """Gọi khi shutdown server."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


# =====================================================
# HELPERS
# =====================================================

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = html_mod.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit].rsplit(" ", 1)[0] + "…"


def _format_results(results: list) -> str | None:
    """Format kết quả search thành text gọn cho TTS."""
    lines = []
    for i, res in enumerate(results, 1):
        title = _clean_text(res.get("title") or "")
        content = _clean_text(
            res.get("content") or res.get("desc") or res.get("body") or "")
        url = (res.get("url") or res.get("link") or "").strip()
        if not title and not content:
            continue
        content = _truncate_words(content, 400)
        block = f"[{i}] {title}"
        if content:
            block += f"\n    {content}"
        if url:
            block += f"\n    {url}"
        lines.append(block)
    return "\n".join(lines) if lines else None


# =====================================================
# WEATHER (không cần search)
# =====================================================

_geocode_cache: dict[str, dict] = {}


async def _geocode(city: str) -> dict:
    key = city.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    client = await _http()
    r = await client.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "vi"},
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        raise ValueError(f"Không tìm thấy thành phố '{city}'")
    loc = data["results"][0]
    out = {
        "name": loc.get("name", city),
        "lat": loc["latitude"],
        "lon": loc["longitude"],
    }
    _geocode_cache[key] = out
    return out


async def _tool_get_weather(city: str) -> str:
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,wind_speed_10m,weather_code"
                ),
                "timezone": "Asia/Ho_Chi_Minh",
            },
        )
        r.raise_for_status()
        w = r.json()["current"]
        desc = WMO_CODES.get(w["weather_code"], "Không rõ")
        return (
            f"Thời tiết {loc['name']}: {desc}, "
            f"{w['temperature_2m']}°C (cảm giác {w['apparent_temperature']}°C), "
            f"độ ẩm {w['relative_humidity_2m']}%, "
            f"gió {w['wind_speed_10m']} km/h."
        )
    except Exception as e:
        logger.error(f"get_weather lỗi: {e}")
        return f"Không lấy được thời tiết cho {city}."


async def _tool_get_forecast(city: str, days: int = 3) -> str:
    days = max(1, min(7, int(days)))
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weather_code"
                ),
                "forecast_days": days,
                "timezone": "Asia/Ho_Chi_Minh",
            },
        )
        r.raise_for_status()
        d = r.json()["daily"]

        lines = [f"Dự báo {loc['name']} {days} ngày tới:"]
        rains = d["precipitation_probability_max"]

        for i in range(days):
            y, mo, dd = map(int, d["time"][i].split("-"))
            wd = WEEKDAYS_VI[date_cls(y, mo, dd).weekday()]
            # ✅ FIX: rains[i] có thể None → default 0
            prob = rains[i] if rains[i] is not None else 0
            t_min = d["temperature_2m_min"][i]
            t_max = d["temperature_2m_max"][i]
            lines.append(
                f"  {wd} {dd}/{mo}: "
                f"{t_min}°C - {t_max}°C, "
                f"{WMO_CODES.get(d['weather_code'][i], '')}, mưa {prob}%"
            )

        # ✅ FIX: filter None trước khi min/max
        valid_rains = [p for p in rains if p is not None]
        max_rain = max(valid_rains) if valid_rains else 0
        rain_note = (
            "có mưa rõ rệt" if max_rain >= 60
            else "có thể có mưa" if max_rain >= 30
            else "ít có mưa"
        )
        valid_tmin = [x for x in d["temperature_2m_min"] if x is not None]
        valid_tmax = [x for x in d["temperature_2m_max"] if x is not None]
        tmin = min(valid_tmin) if valid_tmin else 0
        tmax = max(valid_tmax) if valid_tmax else 0

        lines.append(
            f"\nTổng quan: {days} ngày tới {rain_note}, "
            f"nhiệt độ {tmin:.0f}°C - {tmax:.0f}°C."
        )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_forecast lỗi: {e}")
        return f"Không lấy được dự báo cho {city}."


# =====================================================
# SEARXNG
# =====================================================

async def _search_searxng(
    query: str,
    extra_params: dict | None = None,
) -> str | None:
    url = _cfg("searxng_url")
    if not url:
        return None
    try:
        params = {
            "q": query,
            "format": "json",
            "language": "vi-VN",
            "safesearch": 0,
        }
        if extra_params:
            params.update(extra_params)

        client = await _http()
        r = await client.get(url, params=params)

        if r.status_code == 403:
            logger.warning("SearXNG 403 — JSON chưa bật trong settings.yml")
            return None
        r.raise_for_status()

        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            logger.warning(f"SearXNG trả {ctype!r}, không phải JSON")
            return None

        results = r.json().get("results", [])
        max_n = _cfg("search_max_results", 5)
        results = results[:max_n]
        if not results:
            return None
        return _format_results(results)
    except Exception as e:
        logger.warning(f"SearXNG lỗi: {e}")
        return None


def _subject_to_searxng_params(subject: str) -> dict:
    base = {"language": "vi-VN", "safesearch": 0}
    if subject in ("person", "concept", "place"):
        return {**base, "engines": "wikipedia", "categories": "general"}
    if subject == "news":
        return {**base, "categories": "news", "time_range": "day"}
    if subject == "howto":
        return {**base, "categories": "general", "engines": "google,bing"}
    return {**base, "categories": "general"}


# =====================================================
# WIKIPEDIA
# =====================================================

WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH = "https://{lang}.wikipedia.org/w/api.php"


async def _wiki_summary(title: str, lang: str = "vi") -> dict | None:
    try:
        client = await _http()
        r = await client.get(
            WIKI_SUMMARY.format(lang=lang, title=title.replace(" ", "_")),
            headers={"Accept": "application/json"},
            timeout=8.0,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if data.get("type") == "disambiguation":
            return None
        return {
            "title": data.get("title"),
            "extract": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }
    except Exception as e:
        logger.debug(f"Wiki summary lỗi: {e}")
        return None


async def _wiki_search(query: str, lang: str = "vi", limit: int = 3) -> list:
    try:
        client = await _http()
        r = await client.get(
            WIKI_SEARCH.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "utf8": 1,
            },
            timeout=8.0,
        )
        r.raise_for_status()
        return r.json().get("query", {}).get("search", [])
    except Exception as e:
        logger.debug(f"Wiki search lỗi: {e}")
        return []


async def _search_wikipedia(query: str) -> str | None:
    lang = _cfg("wiki_lang", "vi") or "vi"

    # Thử direct lookup trước
    direct = await _wiki_summary(query, lang)
    if direct and direct.get("extract"):
        return (
            f"〖Wikipedia〗{direct['title']}\n"
            f"{direct['extract']}\n"
            f"{direct.get('url', '')}"
        )

    # Fallback: search rồi lấy summary
    results = await _wiki_search(query, lang, limit=3)
    if not results:
        return None

    top = results[0].get("title", "")
    if not top:
        return None

    summary = await _wiki_summary(top, lang)
    if not summary or not summary.get("extract"):
        snippet = re.sub(r"<[^>]+>", "", results[0].get("snippet", ""))
        return f"〖Wikipedia〗{top}\n{snippet}"

    return (
        f"〖Wikipedia〗{summary['title']}\n"
        f"{summary['extract']}\n"
        f"{summary.get('url', '')}"
    )


# =====================================================
# TAVILY
# =====================================================

async def _search_tavily(
    query: str,
    time_range: str | None = None,
    include_answer: bool = True,
) -> str | None:
    key = _cfg("tavily_api_key")
    if not key:
        return None

    try:
        body = {
            "api_key": key,
            "query": query,
            "search_depth": "advanced" if include_answer else "basic",
            "max_results": _cfg("search_max_results", 3),
            "include_answer": "advanced" if include_answer else False,
            "include_raw_content": False,
        }
        if time_range:
            body["time_range"] = time_range

        client = await _http()
        r = await client.post("https://api.tavily.com/search", json=body)

        if r.status_code == 429:
            logger.warning("⚠️ Tavily hết credit")
            return None
        if r.status_code == 401:
            logger.warning("⚠️ Tavily API key sai")
            return None
        r.raise_for_status()

        data = r.json()
        parts = []

        # Ưu tiên answer — ngắn gọn, đủ ý cho TTS
        answer = (data.get("answer") or "").strip()
        if answer:
            if len(answer) > 350:
                answer = answer[:350].rsplit(" ", 1)[0] + "..."
            parts.append(answer)

        # Fallback: top results nếu không có answer
        if not answer:
            results = data.get("results", [])[:2]
            for x in results:
                title = (x.get("title") or "").strip()
                content = (x.get("content") or "").strip()[:200]
                if content:
                    parts.append(f"{title}: {content}" if title else content)

        return "\n".join(parts) if parts else None

    except Exception as e:
        logger.warning(f"Tavily lỗi: {e}")
        return None


# =====================================================
# DDGS FALLBACK
# =====================================================

async def _search_ddgs(query: str) -> str | None:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        def _do(backend):
            with DDGS() as d:
                return list(d.text(query, max_results=5, backend=backend))

        for backend in ["brave", "bing", "yandex", "auto"]:
            try:
                results = await asyncio.to_thread(_do, backend)
                if results:
                    parts = [
                        f"{r.get('title', '')}: {r.get('body', '')[:300]}"
                        for r in results[:3] if r.get("title")
                    ]
                    if parts:
                        return " ".join(parts)
            except Exception:
                continue
        return None
    except Exception as e:
        logger.warning(f"ddgs lỗi: {e}")
        return None


# =====================================================
# MAIN ROUTER
# =====================================================

async def _tool_web_search(query: str) -> str:
    subject = _classify_subject(query)
    has_tavily = bool(_cfg("tavily_api_key"))
    logger.info(f"🔍 web_search [{subject}] '{query[:60]}'")

    # ─── 1. Tavily cho realtime/product/news/howto ───
    if has_tavily and subject in ("realtime", "product", "news", "howto"):
        time_range = "day" if subject in ("realtime", "news") else None
        result = await _search_tavily(
            query,
            time_range=time_range,
            include_answer=True,
        )
        if result:
            logger.info(f"   ✓ Tavily ({subject})")
            return result
        logger.info("   ↻ Tavily fail → next")

    # ─── 2. Wikipedia cho person/concept/place ───
    if subject in ("person", "concept", "place"):
        result = await _search_wikipedia(query)
        if result:
            logger.info(f"   ✓ Wikipedia ({subject})")
            return result
        logger.info("   ↻ Wiki fail → SearXNG")

    # ─── 3. SearXNG (subject-specific params) ───
    searxng_params = _subject_to_searxng_params(subject)
    result = await _search_searxng(query, extra_params=searxng_params)
    if result:
        logger.info(f"   ✓ SearXNG ({subject})")
        return result

    # ─── 4. SearXNG general fallback (nếu params quá hẹp) ───
    if searxng_params.get("engines") or searxng_params.get("categories") != "general":
        result = await _search_searxng(query, extra_params={"language": "vi-VN"})
        if result:
            logger.info("   ✓ SearXNG (general fallback)")
            return result

    # ─── 5. Tavily rescue (general case) ───
    if has_tavily:
        result = await _search_tavily(query, time_range=None)
        if result:
            logger.info("   ✓ Tavily (rescue)")
            return result

    # ─── 6. ddgs fallback ───
    logger.info("   ↻ Fallback ddgs")
    result = await _search_ddgs(query)
    if result:
        logger.info("   ✓ ddgs")
        return result

    return f"Không tìm thấy thông tin về '{query}'."


# =====================================================
# TIME / DATE
# =====================================================

async def _tool_get_current_time() -> str:
    now = datetime.now()
    return now.strftime(
        f"Bây giờ là %H:%M, ngày %d/%m/%Y ({WEEKDAYS_VI[now.weekday()]})."
    )


def _parse_date(date_str: str) -> date_cls:
    today = date_cls.today()
    s = (date_str or "").strip().lower()

    if s in DATE_ALIASES:
        return today + timedelta(days=DATE_ALIASES[s])

    if s.startswith(("+", "-")) and s[1:].isdigit():
        return today + timedelta(days=int(s))

    WEEKDAY_NAMES = {
        "thứ hai": 0, "thứ 2": 0,
        "thứ ba": 1, "thứ 3": 1,
        "thứ tư": 2, "thứ 4": 2,
        "thứ năm": 3, "thứ 5": 3,
        "thứ sáu": 4, "thứ 6": 4,
        "thứ bảy": 5, "thứ 7": 5,
        "chủ nhật": 6, "cn": 6,
    }
    for name, wd in WEEKDAY_NAMES.items():
        if name in s:
            week_offset = 0
            if "tuần sau" in s or "tuần tới" in s:
                week_offset = 1
            elif "tuần trước" in s:
                week_offset = -1

            monday_this = today - timedelta(days=today.weekday())
            monday_target = monday_this + timedelta(weeks=week_offset)
            target = monday_target + timedelta(days=wd)
            if week_offset == 0 and target < today:
                target += timedelta(days=7)
            return target

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = today.year
        return date_cls(y, mo, d)

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    raise ValueError(f"Không hiểu định dạng ngày: {date_str!r}")


async def _tool_get_weekday(date: str) -> str:
    try:
        d = _parse_date(date)
        wd = WEEKDAYS_VI[d.weekday()]
        delta = (d - date_cls.today()).days

        rel_map = {0: "hôm nay", 1: "ngày mai", 2: "ngày kia", -1: "hôm qua"}
        if delta in rel_map:
            rel = rel_map[delta]
        elif delta > 0:
            rel = f"còn {delta} ngày nữa"
        else:
            rel = f"{abs(delta)} ngày trước"

        return f"{d.strftime('%d/%m/%Y')} là {wd} ({rel})."
    except Exception as e:
        logger.error(f"get_weekday lỗi: {e}")
        return f"Không tra được thứ cho '{date}'. Lỗi: {e}"


async def _tool_days_between(date1: str, date2: str) -> str:
    try:
        d1 = _parse_date(date1)
        d2 = _parse_date(date2)
        delta = (d2 - d1).days
        if delta == 0:
            rel = "cùng một ngày"
        elif delta > 0:
            rel = f"{d2.strftime('%d/%m/%Y')} sau {d1.strftime('%d/%m/%Y')} {delta} ngày"
        else:
            rel = f"{d2.strftime('%d/%m/%Y')} trước {d1.strftime('%d/%m/%Y')} {abs(delta)} ngày"
        return (
            f"Từ {d1.strftime('%d/%m/%Y')} ({WEEKDAYS_VI[d1.weekday()]}) "
            f"đến {d2.strftime('%d/%m/%Y')} ({WEEKDAYS_VI[d2.weekday()]}): "
            f"{abs(delta)} ngày ({rel})."
        )
    except Exception as e:
        logger.error(f"days_between lỗi: {e}")
        return f"Không tính được. Lỗi: {e}"


# =====================================================
# SENSOR STATE IMPORT (nếu chưa có)
# =====================================================

try:
    from app.core.providers.tools import sensor_state
except ImportError:
    sensor_state = None


# =====================================================
# LUNAR CALENDAR (Âm lịch VN)
# =====================================================

async def _tool_get_lunar(date: str = "hôm nay") -> str:
    try:
        from lunardate import LunarDate
    except ImportError:
        return "Lỗi: chưa cài lunardate. Chạy: pip install lunardate"

    try:
        base = _parse_date(date or "hôm nay")
        lunar = LunarDate.fromSolarDate(base.year, base.month, base.day)

        CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu",
               "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
        CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ",
               "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]
        can_year = CAN[(lunar.year - 4) % 10]
        chi_year = CHI[(lunar.year - 4) % 12]

        special = ""
        if lunar.day == 1:
            special = " (mùng 1 đầu tháng âm)"
        elif lunar.day == 15:
            special = " (rằm, ngày 15 âm)"
        elif lunar.day in (29, 30):
            special = " (cuối tháng âm)"

        delta = (base - date_cls.today()).days
        rel_map = {0: "hôm nay", 1: "ngày mai", 2: "ngày kia", -1: "hôm qua"}
        rel = rel_map.get(delta,
                          f"{abs(delta)} ngày nữa" if delta > 0
                          else f"{abs(delta)} ngày trước")

        leap = " nhuận" if getattr(lunar, "isLeapMonth", False) else ""

        return (
            f"Ngày {base.strftime('%d/%m/%Y')} dương lịch {rel} "
            f"tương ứng âm lịch {lunar.day}/{lunar.month}{leap} "
            f"năm {can_year} {chi_year}{special}."
        )
    except Exception as e:
        logger.error(f"get_lunar lỗi: {e}")
        return f"Không tra được âm lịch cho '{date}'. Lỗi: {e}"


# =====================================================
# NEWS (RSS VN)
# =====================================================

NEWS_FEEDS = {
    "vnexpress":  "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tuoitre":    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien":  "https://thanhnien.vn/rss/home.rss",
    "dantri":     "https://dantri.com.vn/rss/home.rss",
}


async def _tool_get_news(category: str = "vnexpress", limit: int = 5) -> str:
    try:
        import feedparser
    except ImportError:
        return "Lỗi: chưa cài feedparser. Chạy: pip install feedparser"

    category = (category or "vnexpress").lower().strip()
    feed_url = NEWS_FEEDS.get(category, NEWS_FEEDS["vnexpress"])
    category = category if category in NEWS_FEEDS else "vnexpress"

    try:
        limit = max(1, min(10, int(limit)))
    except (ValueError, TypeError):
        limit = 5

    def _fetch():
        try:
            return feedparser.parse(feed_url)
        except Exception as e:
            logger.warning(f"feedparser lỗi: {e}")
            return None

    try:
        feed = await asyncio.to_thread(_fetch)
        if not feed or not feed.entries:
            return f"Không lấy được tin tức từ {category}."

        lines = [f"Tin tức mới nhất ({category}):"]
        for i, entry in enumerate(feed.entries[:limit], 1):
            title = _clean_text(entry.get("title", ""))
            if title:
                lines.append(f"  {i}. {title}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_news lỗi: {e}")
        return f"Không lấy được tin tức. Lỗi: {e}"


# =====================================================
# EXCHANGE RATE
# =====================================================

async def _tool_get_exchange_rate(
    currency: str = "USD",
    target: str = "VND",
) -> str:
    currency = (currency or "USD").upper().strip()
    target = (target or "VND").upper().strip()

    try:
        client = await _http()
        r = await client.get(
            "https://api.frankfurter.app/latest",
            params={"from": currency, "to": target},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rates = data.get("rates", {})
        rate = rates.get(target)
        if rate:
            if rate >= 1000:
                rate_str = f"{rate:,.0f}".replace(",", ".")
            else:
                rate_str = f"{rate:.4f}"
            return (
                f"Tỷ giá {currency}/{target}: 1 {currency} = {rate_str} {target}. "
                f"(Cập nhật: {data.get('date', 'không rõ')})"
            )
    except Exception as e:
        logger.warning(f"Frankfurter lỗi: {e}")

    logger.info("   ↻ Exchange rate fallback → web_search")
    return await _tool_web_search(f"tỷ giá {currency} {target} hôm nay")


# =====================================================
# CALCULATE
# =====================================================

async def _tool_calculate(expression: str) -> str:
    try:
        import ast
        import operator

        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.Mod: operator.mod,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
            ast.FloorDiv: operator.floordiv,
        }

        def eval_node(node):
            if isinstance(node, ast.Num):
                return node.n
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.BinOp):
                return ops[type(node.op)](eval_node(node.left), eval_node(node.right))
            if isinstance(node, ast.UnaryOp):
                return ops[type(node.op)](eval_node(node.operand))
            raise ValueError(f"Không hỗ trợ: {type(node).__name__}")

        expr = (expression or "").strip()
        if not expr:
            return "Biểu thức rỗng."

        expr = expr.replace("^", "**")
        expr = re.sub(r"[xX]", "*", expr)
        expr = expr.replace(":", "/")
        expr = re.sub(r"[^\d\+\-\*/%\(\)\.\s]", "", expr)

        if not expr.strip():
            return "Biểu thức không hợp lệ."

        tree = ast.parse(expr, mode="eval")
        result = eval_node(tree.body)

        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 4)

        return f"{expr.strip()} = {result}"
    except Exception as e:
        logger.warning(f"calculate lỗi: {e}")
        return f"Không tính được '{expression}'. Lỗi: {e}"


# =====================================================
# AIR QUALITY (MQ135)
# =====================================================

async def _tool_get_air_quality() -> str:
    if sensor_state is None:
        return "Lỗi: chưa có module sensor_state."

    if not sensor_state.is_fresh(max_age_sec=300):
        return (
            "Chưa có dữ liệu cảm biến không khí. "
            "Kiểm tra ESP32 đã kết nối chưa."
        )

    ppm = sensor_state.get("air_quality_ppm")
    if ppm is None:
        return "Chưa có dữ liệu từ cảm biến MQ135."

    try:
        ppm = float(ppm)
    except (ValueError, TypeError):
        return "Dữ liệu cảm biến không hợp lệ."

    if ppm < 400:
        level = "rất tốt"
        advice = "Không khí trong lành."
    elif ppm < 800:
        level = "tốt"
        advice = "Không khí ổn."
    elif ppm < 1500:
        level = "trung bình"
        advice = "Nên mở cửa sổ cho thoáng."
    elif ppm < 2500:
        level = "kém"
        advice = "Không khí kém, nên thông gió ngay."
    else:
        level = "nguy hiểm"
        advice = "Cảnh báo: không khí rất kém, mở cửa ngay!"

    return (
        f"Chất lượng không khí hiện tại ở mức {level}, "
        f"khoảng {ppm:.0f} ppm. {advice}"
    )

# =====================================================
# MCP — GỬI LỆNH XUỐNG ESP32
# =====================================================

async def _send_mcp_command(
    method: str,
    params: dict = None,
    timeout: float = 3.0,
) -> dict:
    """Gửi lệnh MCP xuống device theo chuẩn JSON-RPC 2.0."""
    import asyncio
    from app.core.mqtt_server import get_mqtt_manager

    manager = get_mqtt_manager()
    if not manager.sessions:
        return {"ok": False, "error": "Không có thiết bị nào kết nối."}

    device_id = list(manager.sessions.keys())[0]
    s = manager.sessions[device_id]
    transport = s["transport"]

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    s["_mcp_future"] = fut

    try:
        await transport.send_json({
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": method,
                    "arguments": params or {},
                },
            },
        })
        logger.info(f"📤 MCP → {device_id}: {method}({params})")

        try:
            reply = await asyncio.wait_for(fut, timeout=timeout)
            logger.info(f"📥 MCP reply: {str(reply)[:200]}")
            return {"ok": True, "device_id": device_id, "reply": reply}
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"Timeout {timeout}s chờ reply"}
    except Exception as e:
        logger.error(f"MCP send lỗi: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        s.pop("_mcp_future", None)


async def _tool_lamp_turn_on() -> str:
    result = await _send_mcp_command("Lamp.TurnOn")
    if result["ok"]:
        return "Đã bật đèn."
    return f"Không bật được đèn: {result.get('error')}"


async def _tool_lamp_turn_off() -> str:
    result = await _send_mcp_command("Lamp.TurnOff")
    if result["ok"]:
        return "Đã tắt đèn."
    return f"Không tắt được đèn: {result.get('error')}"


async def _tool_lamp_set_brightness(brightness: int) -> str:
    brightness = max(0, min(100, int(brightness)))
    result = await _send_mcp_command(
        "Lamp.SetBrightness", {"value": brightness}
    )
    if result["ok"]:
        return f"Đã đặt độ sáng {brightness}%."
    return f"Không đổi được độ sáng: {result.get('error')}"


async def _tool_lamp_set_color_temp(color_temp: int) -> str:
    color_temp = max(0, min(100, int(color_temp)))
    result = await _send_mcp_command(
        "Lamp.SetColorTemp", {"value": color_temp}
    )
    if result["ok"]:
        return f"Đã đặt nhiệt độ màu {color_temp}."
    return f"Không đổi được màu: {result.get('error')}"


async def _tool_get_sensor(sensor: str = "all") -> str:
    if sensor_state is not None:
        if sensor == "all":
            data = sensor_state.get_all()
            if not sensor_state.is_fresh(max_age_sec=300):
                return "Chưa có dữ liệu cảm biến. Kiểm tra ESP32 đã kết nối chưa."

            parts = []
            if data.get("temperature") is not None:
                parts.append(f"nhiệt độ {data['temperature']}°C")
            if data.get("humidity") is not None:
                parts.append(f"độ ẩm {data['humidity']}%")
            if data.get("air_quality_ppm") is not None:
                parts.append(f"không khí {data['air_quality_ppm']} ppm")
            if data.get("light_lux") is not None:
                parts.append(f"ánh sáng {data['light_lux']} lux")
            if data.get("presence") is not None:
                parts.append("có người" if data["presence"] else "không có người")

            return "Phòng hiện tại: " + ", ".join(parts) + "."
        else:
            value = sensor_state.get(sensor)
            if value is None:
                return f"Chưa có dữ liệu {sensor}."
            return f"{sensor} hiện tại: {value}"

    result = await _send_mcp_command("Sensor.Read", {"sensor": sensor})
    if result["ok"]:
        return f"Đã yêu cầu đọc {sensor}."
    return "Không đọc được cảm biến."
```

## `app\core\providers\tools\registry.py`

```python
"""Tool registry."""
import json
from loguru import logger


TOOLS_SCHEMA = [
    # ═══ THỜI TIẾT ═══
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Tra thời tiết HIỆN TẠI của một thành phố. "
                "Dùng khi hỏi: thời tiết Hà Nội, trời có mưa không."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Tên thành phố"}
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast",
            "description": "Dự báo thời tiết nhiều ngày tới (tối đa 7 ngày).",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer", "description": "1-7, mặc định 3"},
                },
                "required": ["city"],
            },
        },
    },
    # ═══ TÌM KIẾM ═══
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Tìm kiếm thông tin trên web: giá vàng, chứng khoán, "
                "tỷ số, tin tức, giá sản phẩm, hoặc bất cứ gì cần "
                "thông tin mới từ internet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Câu truy vấn"}
                },
                "required": ["query"],
            },
        },
    },
    # ═══ THỜI GIAN ═══
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Lấy ngày giờ hiện tại. Dùng khi hỏi mấy giờ.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekday",
            "description": (
                "Tra thứ trong tuần. "
                "VD: 'ngày mai là thứ mấy', '17/9 là thứ mấy'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "Hỗ trợ: '17/9/2026', '2026-09-17', "
                            "'hôm nay', 'ngày mai', 'thứ hai tuần sau', '+3', '-2'."
                        ),
                    }
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "days_between",
            "description": "Tính khoảng cách ngày giữa 2 mốc. VD: 'còn mấy ngày đến Tết'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date1": {"type": "string"},
                    "date2": {"type": "string"},
                },
                "required": ["date1", "date2"],
            },
        },
    },
    # ═══ ÂM LỊCH ═══
    {
        "type": "function",
        "function": {
            "name": "get_lunar",
            "description": (
                "Tra ngày ÂM LỊCH VN. Dùng khi hỏi: âm lịch hôm nay, "
                "ngày rằm, mùng 1, Tết, can chi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Ngày dương. VD: 'hôm nay', 'ngày mai', '17/9/2026'.",
                    }
                },
                "required": [],
            },
        },
    },
    # ═══ TIN TỨC ═══
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Lấy tin tức mới nhất từ báo VN. "
                "Dùng khi hỏi: tin tức, thời sự, bản tin."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "vnexpress, tuoitre, thanhnien, dantri",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số tin 1-10, mặc định 5",
                    },
                },
                "required": [],
            },
        },
    },
    # ═══ TỶ GIÁ ═══
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Tra tỷ giá ngoại tệ. VD: USD, EUR, JPY, CNY.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "description": "Mã ngoại tệ"},
                    "target": {"type": "string", "description": "Mặc định VND"},
                },
                "required": ["currency"],
            },
        },
    },
    # ═══ TÍNH TOÁN ═══
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Tính toán. VD: '2+3*4', '(10+5)/3', '2^10'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"}
                },
                "required": ["expression"],
            },
        },
    },
    # ═══ CẢM BIẾN ═══
    {
        "type": "function",
        "function": {
            "name": "get_air_quality",
            "description": (
                "Đọc chất lượng không khí từ MQ135. "
                "Dùng khi hỏi: không khí thế nào, có ô nhiễm không, "
                "khói bụi, khí gas."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ═══ ĐÈN (MCP) ═══
    {
        "type": "function",
        "function": {
            "name": "lamp_turn_on",
            "description": "Bật đèn bàn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_turn_off",
            "description": "Tắt đèn bàn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_set_brightness",
            "description": "Đặt độ sáng đèn (0-100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "brightness": {"type": "integer", "description": "0-100"}
                },
                "required": ["brightness"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_set_color_temp",
            "description": (
                "Đặt nhiệt độ màu đèn (0-100). "
                "0=vàng ấm, 50=trung tính, 100=trắng lạnh."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "color_temp": {"type": "integer", "description": "0-100"}
                },
                "required": ["color_temp"],
            },
        },
    },
    # ═══ CẢM BIẾN (MCP) ═══
    {
        "type": "function",
        "function": {
            "name": "get_sensor",
            "description": (
                "Đọc cảm biến từ ESP32: nhiệt độ, độ ẩm, "
                "không khí, ánh sáng, hiện diện."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor": {
                        "type": "string",
                        "description": (
                            "Tên cảm biến: temperature, humidity, "
                            "air_quality_ppm, light_lux, presence, all"
                        ),
                    }
                },
                "required": [],
            },
        },
    },
]


async def execute_tool(name: str, arguments) -> str:
    from app.core.providers.tools import impl as _impl
    fn = getattr(_impl, f"_tool_{name}", None)
    if not fn:
        logger.warning(f"Tool không tồn tại: {name}")
        return f"Không có tool '{name}'."

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as e:
            logger.error(f"Tool {name}: JSON không hợp lệ: {e}")
            return f"Tham số cho {name} không phải JSON hợp lệ."

    if not isinstance(arguments, dict):
        arguments = {}

    try:
        return await fn(**arguments)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={arguments}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"
```

## `app\core\providers\tools\sensor_state.py`

```python
"""Sensor state — lưu giá trị cảm biến từ ESP32 gửi lên."""
import time
from threading import Lock
from typing import Optional


_state = {
    "temperature": None,       # °C
    "humidity": None,          # %
    "air_quality_ppm": None,   # MQ135
    "air_quality_level": None, # "tốt" / "kém" / ...
    "light_lux": None,         # lux
    "presence": None,          # bool
    "last_update": 0.0,
}

_lock = Lock()


def update(key: str, value):
    """Cập nhật 1 giá trị. Gọi từ MQTT handler khi ESP32 gửi."""
    with _lock:
        _state[key] = value
        _state["last_update"] = time.time()


def update_bulk(data: dict):
    """Cập nhật nhiều giá trị cùng lúc."""
    with _lock:
        for k, v in data.items():
            if k in _state:
                _state[k] = v
        _state["last_update"] = time.time()


def get(key: str) -> Optional[float]:
    with _lock:
        return _state.get(key)


def get_all() -> dict:
    with _lock:
        return dict(_state)


def is_fresh(max_age_sec: float = 120.0) -> bool:
    """Dữ liệu có mới không (mặc định 2 phút)."""
    with _lock:
        return (time.time() - _state["last_update"]) < max_age_sec
```

## `app\core\providers\tts\edge.py`

```python
"""Edge TTS provider với normalization."""
import asyncio
import time
import re
import edge_tts
from app.core.providers.base import TTSProviderBase, ProviderRegistry


# === Emoji ===
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
    "\U00002700-\U000027BF\U0001F1E0-\U0001F1FF"
    "\U0000FE00-\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)

# === Markdown ===
LIST_MARKER_PATTERN = re.compile(r"(?m)^\s*(?:[*\-+•]|\d+[.)])\s+")
BOLD_ITALIC_PATTERN = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}|_{1,3}([^_\n]+?)_{1,3}")
HEADING_PATTERN = re.compile(r"(?m)^#{1,6}\s+")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+?)`")

# === Normalize ===
DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
TIME_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\b")
PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
DEGREE_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*[CcFf]")
DECIMAL_PATTERN = re.compile(r"\b(\d+)\.(\d{1,2})(?!\d)")
SPECIAL_CHARS_PATTERN = re.compile(r"[*_`~#>\[\]{}()|\\/]+")
MULTI_SPACE_PATTERN = re.compile(r"\s+")


def _replace_date(m):
    d, mo, y = m.group(1), m.group(2), m.group(3)
    return f"{d} tháng {mo} năm {y}" if y else f"{d} tháng {mo}"


def _replace_time(m):
    h, mi = m.group(1), m.group(2)
    return f"{h} giờ" if mi == "00" else f"{h} giờ {mi}"


def _replace_percent(m):
    return f"{m.group(1)} phần trăm"


def _replace_degree(m):
    return f"{m.group(1)} độ C"


def _replace_decimal(m):
    return f"{m.group(1)} phẩy {m.group(2)}"


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\n+", ". ", text)
    text = LIST_MARKER_PATTERN.sub("", text)
    text = BOLD_ITALIC_PATTERN.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = HEADING_PATTERN.sub("", text)
    text = INLINE_CODE_PATTERN.sub(r"\1", text)
    return text


def clean_for_tts(text: str) -> str:
    if not text:
        return ""
    text = _strip_markdown(text)
    text = DATE_PATTERN.sub(_replace_date, text)
    text = TIME_PATTERN.sub(_replace_time, text)
    text = DEGREE_PATTERN.sub(_replace_degree, text)
    text = PERCENT_PATTERN.sub(_replace_percent, text)
    text = DECIMAL_PATTERN.sub(_replace_decimal, text)
    text = EMOJI_PATTERN.sub("", text)
    text = SPECIAL_CHARS_PATTERN.sub("", text)
    text = MULTI_SPACE_PATTERN.sub(" ", text)
    return text.strip()


class EdgeTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not text.strip():
            return b""

        clean = clean_for_tts(text)
        if not clean:
            self.log.debug(f"⚠️ Text rỗng sau normalize: '{text[:60]}'")
            return b""

        if clean != text.strip():
            self.log.debug(f"🧹 '{text[:60]}' → '{clean[:60]}'")

        voice = kwargs.get("voice") or self.config.get("voice")
        rate = self.config.get("rate", "+0%")
        volume = self.config.get("volume", "+0%")
        timeout = self.config.get("request_timeout", 30.0)
        max_retries = self.config.get("max_retries", 3)

        last_err = None
        for attempt in range(max_retries):
            try:
                start = time.perf_counter()
                mp3 = await asyncio.wait_for(
                    self._synth_once(clean, voice, rate, volume),
                    timeout=timeout,
                )
                elapsed = (time.perf_counter() - start) * 1000
                if mp3:
                    self.log.info(f"🔊 Edge [{elapsed:.0f}ms]: {len(mp3)}b")
                    return mp3
            except asyncio.TimeoutError:
                last_err = f"Timeout {timeout}s"
                self.log.warning(f"⏱️ Edge timeout (lần {attempt + 1})")
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                self.log.warning(f"❌ Edge lỗi (lần {attempt + 1}): {last_err}")

            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))

        self.log.error(f"❌ Edge thất bại: {last_err}")
        return b""

    async def _synth_once(self, text, voice, rate, volume) -> bytes:
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, volume=volume
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)


ProviderRegistry.register_tts("edge", EdgeTTSProvider)
```

## `app\core\providers\tts\vieneu.py`

```python
"""VieNeu-TTS provider — dùng curl subprocess + lock timeout.

Bug fix chi tiết:
- Lock có timeout acquire (5s) — nếu request cũ treo, câu mới bỏ qua thay vì chờ vĩnh viễn
- subprocess.Popen + kill() — kill được process con khi treo
- Không dùng requests/httpx (tránh bug SelectorEventLoop)
- Cleanup lock tự động qua try/finally
"""
import asyncio
import json
import subprocess
import sys
import time

from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts


_vieneu_lock = asyncio.Lock()
_consecutive_timeouts = 0
_LOCK_ACQUIRE_TIMEOUT = 5.0
_LAST_LOCK_RELEASE = time.time()

_CURL = "curl.exe" if sys.platform == "win32" else "curl"


class VieNeuTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        global _consecutive_timeouts, _LAST_LOCK_RELEASE

        if not text.strip():
            return b""

        clean = clean_for_tts(text)
        if not clean:
            self.log.debug(f"⚠️ Text rỗng sau normalize: '{text[:60]}'")
            return b""

        url = self.config.get("url", "http://localhost:11436")
        voice = kwargs.get("voice") or self.config.get("voice", "Trúc Ly")
        timeout = min(float(self.config.get("request_timeout", 15.0)), 12.0)

        # Lock có timeout — không chờ vô hạn
        try:
            await asyncio.wait_for(
                _vieneu_lock.acquire(),
                timeout=_LOCK_ACQUIRE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self.log.error(
                f"🚨 VieNeu lock treo >{_LOCK_ACQUIRE_TIMEOUT}s — "
                f"lần release cuối {time.time() - _LAST_LOCK_RELEASE:.1f}s trước. "
                f"Bỏ qua câu này."
            )
            _consecutive_timeouts += 1
            return b""

        t_start = time.perf_counter()
        self.log.debug(f"🔒 VieNeu lock: {clean[:40]!r}")

        try:
            wav_bytes = await self._do_request_async(clean, voice, url, timeout)
            elapsed = (time.perf_counter() - t_start) * 1000

            if not wav_bytes:
                _consecutive_timeouts += 1
                self.log.warning(
                    f"⚠️ VieNeu rỗng sau {elapsed:.0f}ms "
                    f"(#{_consecutive_timeouts})"
                )
                if _consecutive_timeouts >= 3:
                    self.log.error(
                        "🚨 VieNeu treo 3 lần liên tiếp — "
                        "kiểm tra lại VieNeu server!"
                    )
                return b""

            _consecutive_timeouts = 0
            self.log.info(
                f"🔊 VieNeu [{elapsed:.0f}ms] voice={voice!r}: "
                f"{len(wav_bytes)}b | {clean[:40]!r}"
            )
            return wav_bytes

        finally:
            elapsed = (time.perf_counter() - t_start) * 1000
            self.log.debug(f"🔓 VieNeu release sau {elapsed:.0f}ms")
            _LAST_LOCK_RELEASE = time.time()
            _vieneu_lock.release()

    async def _do_request_async(
        self, clean: str, voice: str, url: str, timeout: float
    ) -> bytes:
        """Chạy curl trong thread, có timeout OS-level."""

        def _run() -> bytes:
            payload = json.dumps(
                {"text": clean, "voice": voice},
                ensure_ascii=False,
            ).encode("utf-8")

            proc = subprocess.Popen(
                [
                    _CURL,
                    "-sS",
                    "-X", "POST",
                    f"{url}/tts",
                    "-H", "Content-Type: application/json; charset=utf-8",
                    "-H", "Connection: close",
                    "--no-keepalive",
                    "--max-time", str(timeout),
                    "--data-binary", "@-",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout, stderr = proc.communicate(
                    input=payload,
                    timeout=timeout + 3.0,
                )
            except subprocess.TimeoutExpired:
                self.log.error(f"⏰ curl KILL sau {timeout + 3.0}s")
                proc.kill()
                try:
                    proc.communicate(timeout=2.0)
                except Exception:
                    pass
                return b""

            if proc.returncode != 0:
                err = stderr.decode(errors="ignore")[:200]
                self.log.error(f"❌ curl rc={proc.returncode}: {err}")
                return b""

            return stdout

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=timeout + 5.0,
            )
        except asyncio.TimeoutError:
            self.log.error(f"⏰ to_thread timeout sau {timeout + 5.0}s")
            return b""
        except Exception as e:
            self.log.error(f"❌ VieNeu lỗi: {type(e).__name__}: {e}")
            return b""


ProviderRegistry.register_tts("vieneu", VieNeuTTSProvider)
```

## `app\core\providers\vad\silero.py`

```python
"""
SileroVAD provider — dùng ONNX model để phát hiện giọng nói.
Chính xác hơn EnergyVAD, chống nhiễu tốt.

- Model: silero_vad.onnx (~2MB), chạy CPU
- Frame gốc: 512 samples (32ms @ 16kHz)
- Có buffer nội bộ: chấp nhận bất kỳ kích thước PCM
"""
import collections
from typing import Optional

import numpy as np
import onnxruntime as ort
from loguru import logger


class SileroVAD:
    """Wrapper SileroVAD với buffer nội bộ + double-threshold."""

    # Silero yêu cầu CHÍNH XÁC 512 samples cho mỗi lần inference
    FRAME_SIZE = 512

    def __init__(
        self,
        model_path: str = "models/snakers4_silero-vad/silero_vad.onnx",
        sample_rate: int = 16000,
        # Double-threshold
        threshold: float = 0.5,
        threshold_low: float = 0.2,
        # End-of-speech
        silence_duration_ms: int = 700,
        min_speech_duration_ms: int = 300,
        # Config khác (để tương thích interface EnergyVAD)
        frame_duration_ms: int = 60,
        max_seconds: float = 30.0,
        energy_margin_db: float = 6.0,
        initial_threshold: float = 500.0,
        hangover_ms: int = 200,
        pre_speech_ms: int = 200,
        post_speech_ms: int = 300,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.threshold_low = threshold_low
        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.frame_duration_ms = 32  # Silero frame cố định 32ms
        self.max_samples = int(sample_rate * max_seconds)

        # Buffer PCM thô (chưa qua model)
        self.pcm_buffer = collections.deque()
        self.pcm_buffer_len = 0

        # Buffer audio đã tích lũy khi đang speech
        self.audio_buffer = collections.deque(maxlen=self.max_samples)

        # ONNX session
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3  # Chỉ log lỗi
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )

        # State ONNX (stateful RNN)
        self._state = None
        self._context = None
        self._init_states()

        # VAD decision state
        self.is_in_speech = False
        self.speech_frames = 0     # Số frame speech liên tiếp
        self.silence_frames = 0    # Số frame silence liên tiếp
        self.total_frames = 0

        # Log threshold lần đầu
        logger.info(f"🎤 SileroVAD loaded | model={model_path}")

    def _init_states(self):
        """Reset state ONNX."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def _infer(self, frame: np.ndarray) -> float:
        """Chạy model cho 1 frame 512 samples. Trả về xác suất [0,1]."""
        x = frame.reshape(1, -1).astype(np.float32)
        x = np.concatenate((self._context, x), axis=1)

        ort_inputs = {
            "input": x,
            "state": self._state,
            "sr": np.array(self.sample_rate, dtype=np.int64),
        }
        out, self._state = self.session.run(None, ort_inputs)
        self._context = x[:, -64:]
        return float(out[0][0])

    def push(self, pcm_bytes: bytes) -> bool:
        """
        Nhận PCM bytes (int16 LE).
        Trả về True khi phát hiện kết thúc câu (end-of-speech).
        """
        if not pcm_bytes:
            return False

        # Buffer PCM thô
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        self.pcm_buffer.extend(pcm.tolist())
        self.pcm_buffer_len += len(pcm)

        # Xử lý từng frame 512 samples
        while self.pcm_buffer_len >= self.FRAME_SIZE:
            frame_list = [self.pcm_buffer.popleft() for _ in range(self.FRAME_SIZE)]
            self.pcm_buffer_len -= self.FRAME_SIZE
            frame = np.array(frame_list, dtype=np.float32) / 32768.0

            prob = self._infer(frame)
            self.total_frames += 1

            # === Double-threshold decision ===
            if not self.is_in_speech:
                if prob > self.threshold:
                    self.is_in_speech = True
                    self.speech_frames = 1
                    self.silence_frames = 0
                    logger.debug(f"🎤 Speech start (prob={prob:.2f})")
                else:
                    self.speech_frames = 0
            else:
                if prob < self.threshold_low:
                    self.silence_frames += 1
                    # Vẫn giữ frame vào buffer (để trim sau)
                else:
                    self.silence_frames = 0
                    self.speech_frames += 1

            # Lưu audio vào buffer khi đang speech
            if self.is_in_speech:
                self.audio_buffer.extend(frame_list)

            # === Check end-of-speech ===
            if self.is_in_speech:
                silence_ms = self.silence_frames * self.frame_duration_ms
                speech_ms = self.speech_frames * self.frame_duration_ms

                if (silence_ms >= self.silence_duration_ms
                        and speech_ms >= self.min_speech_duration_ms):
                    logger.info(
                        f"🎤 End-of-speech | speech={speech_ms}ms "
                        f"silence={silence_ms}ms prob={prob:.2f}"
                    )
                    return True

                # Force end nếu speech quá dài
                if speech_ms >= 8000:
                    logger.warning(f"⏰ Max speech (8s) — force end")
                    return True

        return False

    def get_audio(self, trim: bool = True) -> bytes:
        """Trả về PCM đã tích lũy (int16 LE)."""
        if not self.audio_buffer:
            return b""
        arr = np.array(self.audio_buffer, dtype=np.int16)
        return arr.tobytes()

    def reset(self):
        """Reset sau khi xử lý xong 1 câu."""
        self._init_states()
        self.pcm_buffer.clear()
        self.pcm_buffer_len = 0
        self.audio_buffer.clear()
        self.is_in_speech = False
        self.speech_frames = 0
        self.silence_frames = 0

    def has_speech(self) -> bool:
        return self.speech_frames > 0

    def get_stats(self) -> dict:
        return {
            "total_frames": self.total_frames,
            "speech_frames": self.speech_frames,
            "silence_frames": self.silence_frames,
            "is_in_speech": self.is_in_speech,
            "audio_samples": len(self.audio_buffer),
            "threshold": self.threshold,
            "threshold_low": self.threshold_low,
        }


# Alias để tương thích ngược
StreamingAudioBuffer = SileroVAD
```

## `app\core\utils\audio.py`

```python
"""Audio convert helpers."""
import asyncio
import subprocess
from loguru import logger


class AudioConvertError(Exception):
    pass


async def any_to_wav(audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
    def _run():
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-i", "pipe:0",
                    "-f", "wav",
                    "-acodec", "pcm_s16le",
                    "-ac", "1",
                    "-ar", str(sample_rate),
                    "pipe:1",
                ],
                input=audio_bytes,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise AudioConvertError("ffmpeg timeout sau 30s")

        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore")
            logger.error(f"ffmpeg lỗi: {err}")
            raise AudioConvertError(f"ffmpeg failed: {err[:200]}")

        return proc.stdout

    return await asyncio.to_thread(_run)
```

## `app\core\utils\dialogue.py`

```python
"""Dialogue manager."""
import uuid
from typing import List, Dict, Optional
from datetime import datetime


class Message:
    def __init__(self, role, content=None, uniq_id=None,
                 tool_calls=None, tool_call_id=None, is_temporary=False):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.is_temporary = is_temporary

    def to_dict(self) -> dict:
        d = {"role": self.role}
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
            if self.content:
                d["content"] = self.content
        elif self.role == "tool":
            if not self.tool_call_id:
                return {"role": "tool", "content": self.content or ""}
            d["tool_call_id"] = self.tool_call_id
            d["content"] = self.content
        else:
            d["content"] = self.content
        return d


class Dialogue:
    def __init__(self):
        self.dialogue: List[Message] = []

    def put(self, message: Message):
        self.dialogue.append(message)

    def clear(self):
        self.dialogue.clear()

    def __len__(self):
        return len(self.dialogue)

    def _ensure_tool_calls_complete(self) -> List[Message]:
        responded = set()
        for msg in self.dialogue:
            if msg.role == "tool" and msg.tool_call_id:
                responded.add(msg.tool_call_id)

        result: List[Message] = []
        for msg in self.dialogue:
            result.append(msg)
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = (
                        tc.get("id") if isinstance(tc, dict)
                        else getattr(tc, "id", None)
                    )
                    if tc_id and tc_id not in responded:
                        result.append(Message(
                            role="tool",
                            content='{"status": "interrupted"}',
                            tool_call_id=tc_id,
                            is_temporary=True,
                        ))
                        responded.add(tc_id)   # ✅ FIX: tránh duplicate
        return result

    def to_llm_messages(self, memory_str=None, system_prompt=None, max_turns=20):
        complete = self._ensure_tool_calls_complete()
        if len(complete) > max_turns:
            complete = complete[-max_turns:]

        messages = [m.to_dict() for m in complete]

        if system_prompt:
            full_prompt = system_prompt
            if memory_str:
                full_prompt += f"\n\n[Memory]\n{memory_str}"
            full_prompt = full_prompt.replace(
                "{{current_time}}",
                datetime.now().strftime("%H:%M %d/%m/%Y"),
            )
            messages.insert(0, {"role": "system", "content": full_prompt})

        return messages

    def append_user(self, text: str):
        self.put(Message(role="user", content=text))

    def append_assistant(self, text: str, tool_calls=None):
        self.put(Message(role="assistant", content=text, tool_calls=tool_calls))

    def append_tool(self, content: str, tool_call_id: str):
        self.put(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def last_assistant(self) -> Optional[Message]:
        for m in reversed(self.dialogue):
            if m.role == "assistant" and m.content:
                return m
        return None
```

## `app\core\utils\opus_codec.py`

```python
"""
Opus codec — wrapper cho ESP32.
- ESP32 → Backend: decode Opus → PCM (cho ASR)
- Backend → ESP32: encode PCM → Opus

LƯU Ý: Codec giữ state (prediction, gain) → KHÔNG dùng chung giữa các connection.
Mỗi ESP32ConnectionHandler tự tạo 1 instance riêng.
"""
import opuslib


class OpusCodec:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, frame_ms: int = 60):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = int(sample_rate * frame_ms / 1000)  # samples per frame

        # Encoder: PCM → Opus
        self.encoder = opuslib.Encoder(
            sample_rate, channels, opuslib.APPLICATION_VOIP
        )
        self.encoder.bitrate = 16000
        self.encoder.complexity = 5

        # Decoder: Opus → PCM
        self.decoder = opuslib.Decoder(sample_rate, channels)

    def decode(self, opus_bytes: bytes) -> bytes:
        """Opus frame → PCM int16 LE."""
        try:
            return self.decoder.decode(opus_bytes, self.frame_size)
        except Exception as e:
            raise RuntimeError(f"Opus decode lỗi: {e}")


    def encode_frames(self, pcm_data: bytes) -> list:
        """PCM int16 LE → LIST các Opus frame riêng biệt."""
        frame_bytes = self.frame_size * 2
        frames = []
        for i in range(0, len(pcm_data), frame_bytes):
            chunk = pcm_data[i:i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += b"\x00" * (frame_bytes - len(chunk))
            try:
                frames.append(self.encoder.encode(chunk, self.frame_size))
            except Exception as e:
                raise RuntimeError(f"Opus encode lỗi: {e}")
        return frames

    def encode(self, pcm_data: bytes) -> bytes:
        """PCM int16 LE → Opus frames (nhiều frame nếu cần)."""
        frame_bytes = self.frame_size * 2  # int16 = 2 bytes
        out = []
        for i in range(0, len(pcm_data), frame_bytes):
            chunk = pcm_data[i:i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += b"\x00" * (frame_bytes - len(chunk))
            try:
                out.append(self.encoder.encode(chunk, self.frame_size))
            except Exception as e:
                raise RuntimeError(f"Opus encode lỗi: {e}")
        return b"".join(out)


# ✅ FIX: bỏ cache toàn cục — gây race khi nhiều ESP32 cùng lúc.
# Mỗi connection nên tự tạo OpusCodec() riêng.
# Nếu cần dùng chung (chỉ 1 client), có thể dùng hàm dưới đây nhưng KHÔNG khuyến nghị.
```

## `app\core\utils\udp_crypto.py`

```python
"""
AES-CTR cho UDP transport Xiaozhi — bản tương thích server gốc.

Gói UDP từ ESP32 có định dạng:
    [16 bytes nonce][encrypted payload]

Gói UDP server gửi xuống:
    [16 bytes nonce][encrypted payload]

Nonce dùng làm:
    1. Counter block cho AES-CTR
    2. Định danh định tuyến (tra ra device_id)
"""
import secrets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class UdpCrypto:
    def __init__(self, key_hex: str, nonce_hex: str):
        self.key = bytes.fromhex(key_hex)
        self.nonce = bytes.fromhex(nonce_hex)
        assert len(self.key) in (16, 24, 32), f"Key phải 16/24/32 bytes, có {len(self.key)}"
        assert len(self.nonce) == 16, f"Nonce phải 16 bytes, có {len(self.nonce)}"

    def _cipher(self):
        return Cipher(algorithms.AES(self.key), modes.CTR(self.nonce))

    def decrypt_packet(self, packet: bytes) -> bytes:
        """Packet (đã bỏ nonce) -> plaintext payload."""
        if len(packet) == 0:
            return b""
        d = self._cipher().decryptor()
        return d.update(packet) + d.finalize()

    def encrypt_packet(self, payload: bytes) -> bytes:
        """Payload -> encrypted (KHÔNG gồm nonce)."""
        if len(payload) == 0:
            return b""
        e = self._cipher().encryptor()
        return e.update(payload) + e.finalize()



    def decrypt_with_packet_nonce(self, encrypted_payload: bytes, packet_nonce: bytes) -> bytes:
        """Giải mã dùng nonce ĐẦY ĐỦ từ gói tin (16 byte)."""
        if len(packet_nonce) != 16:
            raise ValueError("Packet nonce must be 16 bytes")
        cipher = Cipher(algorithms.AES(self.key), modes.CTR(packet_nonce))
        decryptor = cipher.decryptor()
        return decryptor.update(encrypted_payload) + decryptor.finalize()

    def encrypt_with_packet_nonce(self, payload: bytes, packet_nonce: bytes) -> bytes:
        """Mã hóa dùng nonce ĐẦY ĐỦ từ gói tin."""
        if len(packet_nonce) != 16:
            raise ValueError("Packet nonce must be 16 bytes")
        cipher = Cipher(algorithms.AES(self.key), modes.CTR(packet_nonce))
        encryptor = cipher.encryptor()
        return encryptor.update(payload) + encryptor.finalize()

def generate_key_nonce():
    """Sinh cặp key/nonce mới cho 1 phiên."""
    key_hex = secrets.token_hex(16)
    nonce_hex = secrets.token_hex(16)
    return key_hex, nonce_hex
```

## `app\routes\audio_api.py`

```python
"""API phục vụ file audio."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
AUDIO_DIR = Path("data/audio").resolve()

ROLE_ALIASES = {
    "user": "user",
    "bot": "bot",
    "assistant": "bot",
}


@router.get("/api/audio/{message_id}")
async def get_audio(message_id: int, role: str = "user"):
    folder = ROLE_ALIASES.get(role)
    if not folder:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {list(ROLE_ALIASES.keys())}",
        )

    exts = ["mp3", "wav"] if folder == "bot" else ["wav", "mp3"]

    for ext in exts:
        file_path = AUDIO_DIR / folder / f"{message_id}.{ext}"
        if file_path.exists():
            media_type = "audio/mpeg" if ext == "mp3" else "audio/wav"
            return FileResponse(
                path=str(file_path),
                media_type=media_type,
                filename=f"{folder}_{message_id}.{ext}",
            )

    raise HTTPException(status_code=404, detail="Audio not found")
```

## `app\routes\chat_ws.py`

```python
"""WebSocket route — Device + Session tracking."""
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.connection import ConnectionHandler
from app.core.logger import get_session_logger


router = APIRouter()


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()

    try:
        hello_raw = await ws.receive_text()
        hello = json.loads(hello_raw)
    except Exception:
        await ws.send_json({"type": "error", "text": "Expected hello"})
        await ws.close()
        return

    if hello.get("type") != "hello":
        await ws.send_json({"type": "error", "text": "Expected hello"})
        await ws.close()
        return

    device_id = hello.get("device_id") or "browser-anon"
    client_session_id = hello.get("session_id")

    log = get_session_logger(None, device_id)
    log.info(f"🔌 Client kết nối | device={device_id} | req_session={client_session_id}")

    session_id = None
    handler = None
    is_new = False   # ✅ FIX: tránh undefined

    try:
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "browser")
            session, is_new = await chat_service.resume_or_create_session(
                db, device_id, client_session_id,
            )
            session_id = session.id

        log = get_session_logger(session_id, device_id)
        log.info(f"{'📝 Session mới' if is_new else '♻️  Tiếp tục session'} #{session_id}")

        await ws.send_json({
            "type": "session",
            "session_id": session_id,
            "is_new": is_new,
            "device_id": device_id,
        })

        handler = ConnectionHandler(ws, session_id, device_id)

        if not is_new:
            async with AsyncSessionLocal() as db:
                history = await chat_service.get_session_history(db, session_id)
            handler.load_history(history)
            log.info(f"♻️  Load {len(history)} message từ session cũ")

        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 Client disconnect")
                break

            if "text" in message and message["text"]:
                data = json.loads(message["text"])

                if data.get("type") == "message":
                    user_text = data.get("text", "").strip()
                    if not user_text:
                        continue

                    async with AsyncSessionLocal() as db:
                        await chat_service.save_message(db, session_id, "user", user_text)

                    try:
                        full_response = await handler.handle_text(user_text)
                        if full_response:
                            async with AsyncSessionLocal() as db:
                                await chat_service.save_message(
                                    db, session_id, "assistant", full_response,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3",
                                )
                    except Exception as e:
                        log.exception(f"handle_text lỗi: {e}")
                    finally:
                        await handler.send_end()

                elif data.get("type") == "clear_session":
                    log.info("🔄 Client yêu cầu session mới")
                    async with AsyncSessionLocal() as db:
                        await chat_service.close_session(db, session_id)
                        session, is_new = await chat_service.resume_or_create_session(
                            db, device_id, None,
                        )
                        session_id = session.id
                    log = get_session_logger(session_id, device_id)

                    handler = ConnectionHandler(ws, session_id, device_id)

                    await ws.send_json({
                        "type": "session",
                        "session_id": session_id,
                        "is_new": True,
                        "device_id": device_id,
                    })

            elif "bytes" in message and message["bytes"]:
                audio_bytes = message["bytes"]
                log.info(f"🎤 Audio: {len(audio_bytes)} bytes")

                try:
                    user_text = await handler.handle_voice(audio_bytes)
                    if user_text:
                        async with AsyncSessionLocal() as db:
                            await chat_service.save_message(
                                db, session_id, "user", user_text,
                                audio_bytes=handler.get_captured("user_wav"),
                                audio_ext="wav",
                            )
                            bot_msg = handler.dialogue.last_assistant()
                            if bot_msg and bot_msg.content:
                                await chat_service.save_message(
                                    db, session_id, "assistant", bot_msg.content,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3",
                                )
                except Exception as e:
                    log.exception(f"handle_voice lỗi: {e}")
                finally:
                    await handler.send_end()

    except WebSocketDisconnect:
        log.info("🔌 Client ngắt (WSDisconnect)")
    except RuntimeError as e:
        log.info(f"🔌 Client ngắt: {e}")
    except Exception as e:
        log.exception(f"❌ WS lỗi: {type(e).__name__}: {e}")
    finally:
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception as e:
                log.warning(f"⚠️ Không đóng được session: {e}")
        log.info(f"🔌 Session #{session_id} đóng")
```

## `app\routes\esp32_ws.py`

```python
"""
WebSocket endpoint cho ESP32 — giao thức Xiaozhi v1 + VAD.
"""
import asyncio
import io
import json
import time
import wave
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import config
from app.core.esp32_connection import ESP32ConnectionHandler
from app.core.protocols import WebSocketTransport
from app.core.logger import get_session_logger
from app.core.utils.opus_codec import OpusCodec
from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.providers.vad.energy import EnergyVAD as StreamingAudioBuffer


router = APIRouter()


def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """PCM int16 mono → WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@router.websocket("/xiaozhi/v1/")
async def esp32_ws(ws: WebSocket):
    """WebSocket endpoint cho ESP32 với VAD."""
    await ws.accept()

    device_id = ws.headers.get("Device-Id", "esp32-unknown")
    log = get_session_logger(None, device_id)
    log.info(f"🔌 ESP32 kết nối | device={device_id}")

    session_id = None
    handler = None
    opus = OpusCodec(sample_rate=16000, channels=1)

    # ✅ VAD đọc từ config
    vad_cfg = config.vad_config
    vad = StreamingAudioBuffer(
        sample_rate=16000,
        frame_duration_ms=config.frame_duration,
        silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
        min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
        energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
        initial_threshold=vad_cfg.get("initial_threshold", 500.0),
        hangover_ms=vad_cfg.get("hangover_ms", 200),
        pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
        post_speech_ms=vad_cfg.get("post_speech_ms", 300),
    )

    process_task: Optional[asyncio.Task] = None
    listen_mode = "auto"

    try:
        # ============ 1. Hello ============
        raw = await ws.receive_text()
        hello = json.loads(raw)
        log.info(f"📨 Hello: {hello.get('type')} | version={hello.get('version')}")

        if hello.get("type") != "hello":
            log.error("❌ Message đầu không phải hello")
            await ws.close(code=1002)
            return

        # ✅ Đọc device_id từ header hoặc hello
        device_id = (
            ws.headers.get("Device-Id")
            or hello.get("device_id")
            or hello.get("deviceId")
            or device_id
        )

        # ============ 2. Session ============
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "esp32")
            session, is_new = await chat_service.resume_or_create_session(
                db, device_id, None,
            )
            session_id = session.id

        log = get_session_logger(session_id, device_id)
        log.info(f"📝 Session #{session_id} ({'mới' if is_new else 'tiếp tục'})")

        # ============ 3. Hello response ============
        await ws.send_json({
            "type": "hello",
            "version": 1,
            "session_id": str(session_id),
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        })

        # ============ 4. Handler ============
        handler = ESP32ConnectionHandler(WebSocketTransport(ws), session_id, device_id)

        # ============ 5. Message loop ============
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 ESP32 disconnect")
                if process_task and not process_task.done():
                    process_task.cancel()
                if vad.has_speech():
                    log.info("📤 Xử lý audio còn sót trước khi đóng")
                    pcm = vad.get_audio()
                    vad.reset()
                    if pcm:
                        await _process_vad_audio(handler, session_id, log, pcm)
                break

            # ----- TEXT: JSON control -----
            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    log.warning(f"⚠️ Text không phải JSON: {message['text'][:80]}")
                    continue

                msg_type = data.get("type")

                if msg_type == "listen":
                    mode = (data.get("mode") or "auto").lower()
                    listen_mode = mode
                    wake_text = data.get("text", "")
                    if wake_text:
                        log.info(f"🎤 Wake word: '{wake_text}'")
                    vad.reset()
                    log.info(f"🎤 Listen mode={mode}")

                elif msg_type == "abort":
                    if process_task and not process_task.done():
                        process_task.cancel()
                        try:
                            await process_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        process_task = None
                    handler.abort()
                    vad.reset()
                    log.info("⏹️  ESP32 abort — đã huỷ pipeline")

                elif msg_type == "end":
                    if listen_mode == "manual":
                        if vad.has_speech():
                            pcm = vad.get_audio()
                            vad.reset()
                            if pcm:
                                if process_task and not process_task.done():
                                    log.warning("⚠️ Đang xử lý, bỏ qua end")
                                else:
                                    process_task = asyncio.create_task(
                                        _process_vad_audio(handler, session_id, log, pcm)
                                    )
                        else:
                            vad.reset()

                # ✅ Realtime: stream liên tục, bỏ VAD
                elif msg_type == "realtime":
                    log.info("🎤 Realtime mode — bỏ VAD")

                else:
                    log.debug(f"📨 ESP32 → {msg_type}")

            # ----- BINARY: Opus frames -----
            elif "bytes" in message and message["bytes"]:
                opus_frame = message["bytes"]
                try:
                    pcm = opus.decode(opus_frame)
                except Exception as e:
                    log.warning(f"⚠️ Opus decode lỗi: {e}")
                    continue

                if listen_mode == "manual":
                    vad.push(pcm)
                    continue

                is_end = vad.push(pcm)
                if is_end:
                    log.info(f"🎯 VAD end-of-speech | stats={vad.get_stats()}")
                    pcm_data = vad.get_audio()
                    vad.reset()
                    if pcm_data and (process_task is None or process_task.done()):
                        process_task = asyncio.create_task(
                            _process_vad_audio(handler, session_id, log, pcm_data)
                        )
                    elif pcm_data:
                        log.warning("⚠️ Pipeline đang chạy, bỏ qua VAD end")

    except WebSocketDisconnect:
        log.info("🔌 ESP32 ngắt kết nối")
    except Exception as e:
        log.exception(f"❌ ESP32 WS lỗi: {type(e).__name__}: {e}")
    finally:
        if process_task and not process_task.done():
            process_task.cancel()
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception:
                pass
        log.info(f"🔌 Session #{session_id} đóng")


async def _process_vad_audio(
    handler: ESP32ConnectionHandler,
    session_id: int,
    log,
    pcm: bytes,
):
    """Convert WAV → pipeline."""
    try:
        t0 = time.perf_counter()

        log.info(
            f"🎵 VAD audio: PCM {len(pcm)}b "
            f"(~{len(pcm) / 2 / 16000:.2f}s)"
        )

        wav = _pcm_to_wav(pcm, sample_rate=16000)
        user_text = await handler.handle_voice_wav(wav)

        pipeline_ms = (time.perf_counter() - t0) * 1000
        log.info(f"✅ Pipeline [{pipeline_ms:.0f}ms] | user='{user_text}'")

        if user_text:
            async with AsyncSessionLocal() as db:
                await chat_service.save_message(
                    db, session_id, "user", user_text,
                    audio_bytes=handler.get_captured("user_wav"),
                    audio_ext="wav",
                )
                bot_msg = handler.dialogue.last_assistant()
                if bot_msg and bot_msg.content:
                    await chat_service.save_message(
                        db, session_id, "assistant", bot_msg.content,
                        audio_bytes=handler.get_captured("bot_mp3"),
                        audio_ext="mp3",
                    )

    except asyncio.CancelledError:
        log.info("⏹️ _process_vad_audio bị cancel")
        raise
    except Exception as e:
        log.exception(f"❌ Xử lý VAD audio lỗi: {e}")
```

## `app\routes\web.py`

```python
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.logger import list_session_logs, read_session_log
from app.services import chat as chat_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def root():
    return RedirectResponse(url="/chat")


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    device_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stats = await chat_service.get_stats(db)
    devices = await chat_service.list_devices(db)
    sessions = await chat_service.get_recent_sessions(db, limit=30, device_id=device_id)

    sessions_data = []
    for s in sessions:
        msgs = await chat_service.get_session_messages(db, s.id)
        sessions_data.append({
            "id": s.id,
            "device_id": s.device_id,
            "started_at": s.started_at.strftime("%H:%M %d/%m/%Y") if s.started_at else "",
            "ended_at": s.ended_at.strftime("%H:%M %d/%m/%Y") if s.ended_at else "",
            "message_count": s.message_count,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "audio_path": m.audio_path}
                for m in msgs
            ],
        })

    return templates.TemplateResponse(
        request=request, name="admin.html",
        context={
            "stats": stats,
            "sessions": sessions_data,
            "devices": devices,
            "current_device": device_id,
        },
    )


@router.get("/logs")
async def logs_redirect():
    return RedirectResponse(url="/admin/logs")


@router.get("/admin/log")
async def admin_log_redirect():
    return RedirectResponse(url="/admin/logs")


@router.get("/admin/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    logs = list_session_logs()
    return templates.TemplateResponse(
        request=request, name="logs.html", context={"logs": logs},
    )


@router.get("/admin/logs/{session_id}", response_class=PlainTextResponse)
async def view_session_log(session_id: str, tail: int = 500):
    content = read_session_log(session_id, tail=tail)
    if not content:
        return PlainTextResponse("Không tìm thấy log", status_code=404)
    return PlainTextResponse(content)
```

## `app\services\chat.py`

```python
"""CRUD operations."""
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.models import Device, Session, Message


AUDIO_DIR = Path("data/audio")


# ============ DEVICE ============

async def get_or_create_device(db: AsyncSession, device_id: str, dtype: str = "browser"):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        device = Device(id=device_id, name=device_id, type=dtype)
        db.add(device)
        await db.commit()
        await db.refresh(device)
    else:
        device.last_seen = datetime.utcnow()
        await db.commit()
    return device


async def list_devices(db: AsyncSession):
    result = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    return result.scalars().all()


# ============ SESSION ============

async def create_session(db: AsyncSession, device_id: str):
    s = Session(device_id=device_id)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def get_session(db: AsyncSession, session_id: int):
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def resume_or_create_session(
    db: AsyncSession, device_id: str, client_session_id: int | None,
) -> tuple:
    """Trả về (session, is_new)."""
    resume_sec = config.session_resume_window_minutes * 60

    if client_session_id is not None:
        s = await get_session(db, client_session_id)
        if s and s.device_id == device_id:
            if s.ended_at is None:
                return s, False
            delta = datetime.utcnow() - s.ended_at
            if delta.total_seconds() < resume_sec:
                s.ended_at = None
                await db.commit()
                await db.refresh(s)
                return s, False

    s = await create_session(db, device_id)
    return s, True


async def get_recent_sessions(db: AsyncSession, limit: int = 20, device_id: str = None):
    query = select(Session).order_by(Session.id.desc()).limit(limit)
    if device_id:
        query = select(Session).where(Session.device_id == device_id) \
                               .order_by(Session.id.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def close_session(db: AsyncSession, session_id: int):
    s = await get_session(db, session_id)
    if s and s.ended_at is None:
        s.ended_at = datetime.utcnow()
        await db.commit()


async def delete_session(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id)
    )
    messages = result.scalars().all()

    for msg in messages:
        if msg.audio_path:
            p = Path(msg.audio_path)
            if p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    logger.warning(f"⚠️ Không xóa được {p}: {e}")

    for msg in messages:
        await db.delete(msg)

    s = await get_session(db, session_id)
    if s:
        await db.delete(s)
    await db.commit()


async def cleanup_old_sessions(db: AsyncSession, days: int = 7) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(select(Session).where(Session.started_at < cutoff))
    sessions = result.scalars().all()
    for s in sessions:
        await delete_session(db, s.id)
    return len(sessions)


# ============ MESSAGE ============

async def save_message(
    db: AsyncSession, session_id: int, role: str, content: str,
    audio_bytes: bytes = None, audio_ext: str = "wav",
):
    msg = Message(session_id=session_id, role=role, content=content)
    db.add(msg)

    s = await get_session(db, session_id)
    if s:
        s.message_count = (s.message_count or 0) + 1

    await db.commit()
    await db.refresh(msg)

    if audio_bytes and len(audio_bytes) > 0:
        sub = "user" if role == "user" else "bot"
        audio_dir = AUDIO_DIR / sub
        audio_dir.mkdir(parents=True, exist_ok=True)
        file_path = audio_dir / f"{msg.id}.{audio_ext}"

        try:
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
            msg.audio_path = str(file_path).replace("\\", "/")
            await db.commit()
            return msg, file_path
        except Exception as e:
            logger.error(f"⚠️ Lỗi lưu audio: {e}")

    return msg, None


async def get_session_history(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    )
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]


async def get_session_messages(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    )
    return result.scalars().all()


async def get_stats(db: AsyncSession):
    d = await db.execute(select(func.count(Device.id)))
    s = await db.execute(select(func.count(Session.id)))
    m = await db.execute(select(func.count(Message.id)))
    return {
        "devices": d.scalar() or 0,
        "sessions": s.scalar() or 0,
        "messages": m.scalar() or 0,
    }
```

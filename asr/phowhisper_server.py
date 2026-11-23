"""PhoWhisper ASR Server - Tối ưu soundfile + Chống ảo giác khoảng lặng"""
import os
import re
import time
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
import uvicorn
import torch
import soundfile as sf
import numpy as np
import soxr
from transformers import pipeline

MODEL = os.getenv("PHOWHISPER_MODEL", "vinai/PhoWhisper-medium")
DEVICE = os.getenv("PHOWHISPER_DEVICE", "cuda")
HOST = "0.0.0.0"
PORT = 11435

# Ngưỡng năng lượng tối thiểu để coi là có giọng nói (tinh chỉnh 0.005 - 0.015 tùy độ ồn mic)
MIN_RMS_THRESHOLD = float(os.getenv("ASR_MIN_RMS", "0.008"))

# Các cụm từ ảo giác kinh điển của PhoWhisper khi gặp nhiễu nền / khoảng lặng
HALLUCINATION_PATTERNS = [
    r"dự kiến thành phố hồ chí minh",
    r"tôi thường xuyên nhận nhiệm vụ đưa con đi học",
    r"cảm ơn các bạn đã theo dõi",
    r"hãy đăng ký kênh",
    r"subscribe",
    r"nhiều luồng",
    r"cao bằng",
]

transcriber = None


def is_hallucination(text: str) -> bool:
    """Phát hiện chuỗi rỗng, chuỗi lặp từ bất thường hoặc câu mẫu ảo giác."""
    t = text.strip().lower()
    if len(t) < 2:
        return True

    # 1. Kiểm tra các cụm ảo giác phổ biến
    for pat in HALLUCINATION_PATTERNS:
        if re.search(pat, t):
            return True

    # 2. Kiểm tra hiện tượng lặp cụm từ liên tiếp (VD: "A B C A B C")
    words = re.findall(r"\w+", t)
    if len(words) >= 6:
        half = len(words) // 2
        if words[:half] == words[half : half * 2]:
            return True
        # Tỷ lệ từ duy nhất quá thấp (< 40%) -> lặp từ vô nghĩa
        if len(set(words)) / len(words) < 0.4:
            return True

    return False


@asynccontextmanager
async def lifespan(app):
    global transcriber
    print(f"⏳ Đang tải {MODEL} trên {DEVICE}...")
    start = time.time()

    transcriber = pipeline(
        "automatic-speech-recognition",
        model=MODEL,
        device=0 if DEVICE == "cuda" else -1,
        dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
    )

    print(f"✅ Sẵn sàng sau {time.time() - start:.2f}s | Device: {DEVICE}")
    if DEVICE == "cuda":
        print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")

    yield
    print("👋 ASR server dừng")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "model": MODEL, "device": DEVICE}


@app.get("/health")
async def health():
    return {"status": "healthy" if transcriber is not None else "loading"}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default=MODEL),
    language: str = Form(default="vi"),
):
    if transcriber is None:
        return JSONResponse(status_code=503, content={"error": "Model chưa sẵn sàng"})

    temp_path = None
    try:
        content = await file.read()
        if len(content) == 0:
            raise ValueError("File rỗng")

        suffix = os.path.splitext(file.filename or "")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            temp_path = tmp.name

        # ⚡ Đọc audio bằng soundfile
        t_load = time.perf_counter()
        audio, sr = sf.read(temp_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            audio = soxr.resample(audio, sr, 16000).astype(np.float32)
        load_ms = (time.perf_counter() - t_load) * 1000

        if len(audio) < 16000 * 0.3:
            return {"text": ""}

        # 1️⃣ Lớp 1: Kiểm tra năng lượng RMS — bỏ qua ngay nếu chỉ là khoảng lặng
        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms < MIN_RMS_THRESHOLD:
            print(f"🔇 Bỏ qua khoảng lặng (rms={rms:.5f} < {MIN_RMS_THRESHOLD})")
            return {"text": ""}

        # 2️⃣ Lớp 2: ASR inference với tham số chống lặp & lọc khoảng lặng
        t_infer = time.perf_counter()
        result = transcriber(
            audio,
            generate_kwargs={
                "language": language,
                "task": "transcribe",
                # Transformers 5.x can expose a null generation temperature for
                # Whisper; fallback scoring compares it with zero, so set it explicitly.
                "temperature": 0.0,
                "no_speech_threshold": 0.6,
                "compression_ratio_threshold": 2.2,
                "logprob_threshold": -1.0,
                "repetition_penalty": 1.15,
                "no_repeat_ngram_size": 4,
            },
        )
        infer_ms = (time.perf_counter() - t_infer) * 1000

        text = result["text"].strip()

        # 3️⃣ Lớp 3: Lọc hậu xử lý nếu vẫn dính ảo giác lặp từ
        if is_hallucination(text):
            print(f"🚫 Chặn ảo giác (rms={rms:.5f}): {text}")
            return {"text": ""}

        print(f"⏱️ load={load_ms:.0f}ms infer={infer_ms:.0f}ms rms={rms:.4f} | {text}")
        return {"text": text}

    except Exception as e:
        import traceback
        print(f"❌ LỖI: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)      
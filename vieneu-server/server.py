"""
VieNeu-TTS Server — FastAPI wrapper chạy port 11436.
Giọng mặc định: Trúc Ly (Nữ · Bắc · Tự nhiên).

Chạy CPU 100% — RTX 5060 (sm_120) chưa được PyTorch stable hỗ trợ.
"""
import os

# ⭐ Ép ẩn GPU trước khi import torch (để tránh warning)
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import io
import time
import wave
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel

from vieneu import Vieneu


# =====================================================
# CONFIG
# =====================================================

HOST = "0.0.0.0"
PORT = 11436
DEFAULT_VOICE = "Trúc Ly"
SAMPLE_RATE = 48000

# Bắt buộc cho CPU mode
DEVICE = "cpu"
DTYPE = torch.float32   # CPU không hỗ trợ bfloat16 tốt


# =====================================================
# GLOBAL STATE
# =====================================================

_tts: Optional[Vieneu] = None
_voices_cache: list = []
_model_info: str = "unknown"


# =====================================================
# HELPERS
# =====================================================

def _detect_model_info(tts) -> str:
    """Cố gắng lấy tên model từ SDK."""
    candidates = [
        "backbone_repo",
        "model_name",
        "model_path",
        "repo_id",
    ]

    # Thử trên chính _tts
    for attr in candidates:
        if hasattr(tts, attr):
            val = getattr(tts, attr)
            if val:
                return str(val)

    # Thử trên engine (nếu có)
    if hasattr(tts, "engine"):
        engine = tts.engine
        for attr in candidates:
            if hasattr(engine, attr):
                val = getattr(engine, attr)
                if val:
                    return str(val)

        # Thử tìm trong các attribute phụ
        if hasattr(engine, "model"):
            model = engine.model
            if hasattr(model, "name_or_path"):
                return str(model.name_or_path)
            if hasattr(model, "config") and hasattr(model.config, "_name_or_path"):
                return str(model.config._name_or_path)

    return "unknown"


def _numpy_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    if audio.dtype in (np.float32, np.float64):
        audio = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    elif audio.dtype != np.int16:
        audio = audio.astype(np.int16)

    channels = 1 if audio.ndim == 1 else audio.shape[1]

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())

    return buf.getvalue()


# =====================================================
# LIFESPAN
# =====================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tts, _voices_cache, _model_info

    logger.info(f"🔧 Đang khởi tạo VieNeu-TTS (device={DEVICE}, dtype={DTYPE})...")
    start = time.time()

    try:
        _tts = Vieneu(
            device=DEVICE,
            dtype=DTYPE,
            
        )
        logger.success(f"✅ VieNeu-TTS sẵn sàng sau {time.time() - start:.1f}s")
    except TypeError as e:
        logger.warning(f"⚠️ SDK không nhận dtype ({e}), chỉ truyền device...")
        _tts = Vieneu(device=DEVICE)
        logger.success(f"✅ VieNeu-TTS sẵn sàng sau {time.time() - start:.1f}s")
    except Exception as e:
        logger.exception(f"❌ Khởi tạo thất bại: {e}")
        raise

    # ⭐ Detect model info
    _model_info = _detect_model_info(_tts)
    logger.info(f"📦 Model: {_model_info}")

    # Load danh sách giọng
    try:
        _voices_cache = [
            {"id": vid, "label": label}
            for label, vid in _tts.list_preset_voices()
        ]
        logger.info(f"🎙️  Load {len(_voices_cache)} giọng có sẵn")
        logger.info(f"🎯 Giọng mặc định: {DEFAULT_VOICE!r}")
    except Exception as e:
        logger.warning(f"⚠️ Không load được danh sách giọng: {e}")

    # Warmup
    try:
        logger.info("🔥 Warmup TTS...")
        t0 = time.perf_counter()
        _tts.infer("Xin chào", voice=DEFAULT_VOICE)
        logger.success(f"✅ Warmup xong sau {(time.perf_counter() - t0):.2f}s")
    except Exception as e:
        logger.warning(f"⚠️ Warmup lỗi: {e}")

    yield

    logger.info("👋 VieNeu-TTS server dừng")
    if _tts:
        try:
            _tts.close()
        except Exception:
            pass


app = FastAPI(title="VieNeu-TTS Server", version="1.0.0", lifespan=lifespan)


# =====================================================
# SCHEMAS
# =====================================================

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    speed: float = 1.0


# =====================================================
# ROUTES
# =====================================================

@app.get("/health")
async def health():
    return {
        "status": "ok" if _tts is not None else "loading",
        "voices_count": len(_voices_cache),
        "default_voice": DEFAULT_VOICE,
        "device": DEVICE,
        "dtype": str(DTYPE),
        "model": _model_info,
    }


@app.get("/voices")
async def list_voices():
    return {"voices": _voices_cache, "default": DEFAULT_VOICE}


@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    if _tts is None:
        raise HTTPException(status_code=503, detail="Model chưa sẵn sàng")

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text rỗng")

    voice = req.voice or DEFAULT_VOICE

    try:
        start = time.perf_counter()
        audio = _tts.infer(text, voice=voice)
        elapsed = (time.perf_counter() - start) * 1000

        if not isinstance(audio, np.ndarray):
            audio = np.array(audio)

        wav_bytes = _numpy_to_wav_bytes(audio, SAMPLE_RATE)

        logger.info(
            f"🔊 TTS [{elapsed:.0f}ms] voice={voice!r} "
            f"text={text[:40]!r} → {len(wav_bytes)} bytes WAV"
        )

        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "X-TTS-Voice": voice,
                "X-TTS-Duration-Ms": f"{elapsed:.0f}",
            },
        )

    except Exception as e:
        logger.exception(f"❌ TTS lỗi: {e}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"🌐 VieNeu-TTS server: http://{HOST}:{PORT}")
    logger.info(f"   Device: {DEVICE} | Dtype: {DTYPE}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
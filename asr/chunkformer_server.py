"""ChunkFormer ASR server with the PhoWhisper-compatible transcription API."""
import asyncio
import os
import tempfile
import time
import wave
from array import array
from contextlib import asynccontextmanager
from pathlib import Path

# The top-level launcher forces offline mode for the other local services.
# ChunkFormer needs Hub access on first startup unless its checkpoint is cached.
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from chunkformer import ChunkFormerModel

MODEL_ID = os.getenv("CHUNKFORMER_MODEL", "khanhld/chunkformer-ctc-large-vie")
DEVICE = os.getenv("CHUNKFORMER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
HOST = "0.0.0.0"
PORT = 11435
CHUNK_SIZE = int(os.getenv("CHUNKFORMER_CHUNK_SIZE", "64"))
LEFT_CONTEXT_SIZE = int(os.getenv("CHUNKFORMER_LEFT_CONTEXT_SIZE", "128"))
RIGHT_CONTEXT_SIZE = int(os.getenv("CHUNKFORMER_RIGHT_CONTEXT_SIZE", "128"))

model = None
_inference_lock = asyncio.Lock()
_warmup_audio_path = None


def _create_warmup_wav() -> str:
    """Create a short silent WAV so first-request initialization happens at startup."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp:
        path = temp.name
    samples = array("h", [0] * 16000)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(samples.tobytes())
    return path


def _warmup_model():
    # Warm kernels / CUDA context with a short synthetic audio clip.
    model.endless_decode(
        audio_path=_warmup_audio_path,
        chunk_size=CHUNK_SIZE,
        left_context_size=LEFT_CONTEXT_SIZE,
        right_context_size=RIGHT_CONTEXT_SIZE,
        return_timestamps=False,
    )


@asynccontextmanager
async def lifespan(app):
    global model, _warmup_audio_path
    print(f"⏳ Đang tải {MODEL_ID} trên {DEVICE}...")
    started = time.perf_counter()
    model = ChunkFormerModel.from_pretrained(MODEL_ID)
    model = model.to(torch.device(DEVICE))
    model.eval()
    if DEVICE.startswith("cuda"):
        print(f"🎮 GPU: {torch.cuda.get_device_name(torch.device(DEVICE))}")

    # Move first-call CUDA/kernel initialization into startup instead of first user request.
    _warmup_audio_path = _create_warmup_wav()
    async with _inference_lock:
        await asyncio.to_thread(_warmup_model)
    try:
        os.remove(_warmup_audio_path)
    except OSError:
        pass
    _warmup_audio_path = None

    print(f"✅ ChunkFormer sẵn sàng sau {time.perf_counter() - started:.1f}s | Device: {DEVICE}")
    yield
    model = None
    print("👋 ChunkFormer ASR server dừng")


app = FastAPI(lifespan=lifespan)


def _text_from_result(result) -> str:
    """Normalize ChunkFormer text or timestamped segment results to plain text."""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("decode", "text", "transcription"):
            value = result.get(key)
            if isinstance(value, str):
                return value.strip()
        return " ".join(filter(None, (_text_from_result(v) for v in result.values()))).strip()
    if isinstance(result, (list, tuple)):
        return " ".join(filter(None, (_text_from_result(item) for item in result))).strip()
    return ""


@app.get("/")
async def root():
    return {"status": "ok", "model": MODEL_ID, "device": DEVICE}


@app.get("/health")
async def health():
    return {"status": "healthy" if model is not None else "loading"}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model_name: str = Form(default=MODEL_ID, alias="model"),
    language: str = Form(default="vi"),
):
    if model is None:
        return JSONResponse(status_code=503, content={"error": "Model chưa sẵn sàng"})

    temp_path = None
    try:
        content = await file.read()
        if not content:
            return {"text": ""}
        suffix = Path(file.filename or "audio.wav").suffix or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(content)
            temp_path = temp.name

        started = time.perf_counter()
        # The Xiaozhi provider sends the language field; this checkpoint is Vietnamese-only.
        async with _inference_lock:
            result = await asyncio.to_thread(
                model.endless_decode,
                audio_path=temp_path,
                chunk_size=CHUNK_SIZE,
                left_context_size=LEFT_CONTEXT_SIZE,
                right_context_size=RIGHT_CONTEXT_SIZE,
                return_timestamps=False,
            )
        text = _text_from_result(result)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"⏱️ infer={elapsed_ms:.0f}ms language={language} model={model_name} | {text}")
        return {"text": text}
    except Exception as exc:
        import traceback
        print(f"❌ ChunkFormer ASR lỗi: {exc}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(exc), "type": type(exc).__name__})
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)

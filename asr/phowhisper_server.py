import os
import time
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
import uvicorn
import torch
import librosa
from transformers import pipeline

MODEL = os.getenv("PHOWHISPER_MODEL", "vinai/PhoWhisper-small")
DEVICE = os.getenv("PHOWHISPER_DEVICE", "cuda")
HOST = "0.0.0.0"
PORT = 11435

transcriber = None


@asynccontextmanager
async def lifespan(app):
    global transcriber
    print(f"⏳ Đang tải {MODEL} trên {DEVICE}...")
    start = time.time()

    transcriber = pipeline(
        "automatic-speech-recognition",
        model=MODEL,
        device=0 if DEVICE == "cuda" else -1,
        torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
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

        # Load audio (librosa tự resample về 16kHz mono)
        audio, sr = librosa.load(temp_path, sr=16000, mono=True)

        if len(audio) < 16000 * 0.3:
            raise ValueError(f"Audio quá ngắn ({len(audio)/sr:.2f}s)")

        # ASR
        start = time.time()
        result = transcriber(
            audio,
            generate_kwargs={"language": language, "task": "transcribe"},
        )
        elapsed = time.time() - start

        text = result["text"].strip()
        print(f"✅ [{elapsed:.2f}s] {text}")

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
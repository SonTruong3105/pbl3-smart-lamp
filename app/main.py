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

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

from app.core.signal_handler import install as install_signal_handler
install_signal_handler()
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
                    **({"keep_alive": config.llm_keep_alive} if config.llm_keep_alive else {}),
                    "options": {
                        k: v for k, v in {
                            "num_predict": 1,
                            "num_ctx": config.llm_num_ctx,
                            "num_batch": config.llm_num_batch,
                        }.items() if v is not None
                    },
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

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _warmup_llm(), _warmup_tts(), _warmup_asr(),
                return_exceptions=True,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("⚠️ Warmup timeout 120s — bỏ qua")

    mqtt_mgr = get_mqtt_manager()
    await mqtt_mgr.start()

    # Scheduler + automation rules
    _sched = None
    try:
        from app.core.scheduler import get_scheduler
        _sched_cfg = config._get("scheduler", default={}) or {}
        if _sched_cfg.get("enabled", True):
            _sched = get_scheduler()
            if _sched is not None:
                _sched.start()
                logger.info("Scheduler started")
                try:
                    from app.core.automation import check_rules
                    _interval = config._get(
                        "lamp_automation", "check_interval_sec", default=30
                    )
                    _sched.add_job(
                        check_rules, "interval",
                        seconds=_interval, id="automation_tick",
                    )
                    logger.info(f"Automation rules: moi {_interval}s")
                except Exception as e:
                    logger.warning(f"Automation rules loi: {e}")
            else:
                logger.warning("Scheduler disabled - cai: pip install apscheduler")
    except Exception as e:
        logger.warning(f"Scheduler setup loi: {e}")

    # Adaptive lighting — áp dụng profile giờ hiện tại 1 lần khi start
    try:
        _la_cfg = config._get("lamp_automation", default={}) or {}
        if _la_cfg.get("adaptive_lighting", True):
            from app.core.lamp_automation import apply_time_profile
            # Chờ 5s để MQTT device kịp kết nối
            async def _apply_adaptive_later():
                import asyncio as _aio
                await _aio.sleep(5.0)
                await apply_time_profile(logger)
            import asyncio as _aio
            _aio.create_task(_apply_adaptive_later())
            logger.info("Adaptive lighting: sẽ áp dụng sau 5s")
    except Exception as e:
        logger.warning(f"Adaptive lighting setup loi: {e}")

    logger.info(f"🌐 Mở http://localhost:{config.port}/chat")
    yield

    if _sched is not None:
        try:
            _sched.shutdown()
        except Exception:
            pass
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
    """Health check chi tiet - kiem tra LLM, ASR, TTS, MQTT."""
    checks = {"status": "ok", "version": config.version}

    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(config.llm_url.replace("/api/chat", "/api/tags"))
            checks["llm"] = "ok" if r.status_code == 200 else "down"
    except Exception:
        checks["llm"] = "down"

    try:
        asr_base = config.asr_url.rsplit("/v1/", 1)[0]
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{asr_base}/health")
            checks["asr"] = "ok" if r.status_code == 200 else "down"
    except Exception:
        checks["asr"] = "down"

    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{config.tts_vieneu_url}/health")
            checks["tts"] = "ok" if r.status_code == 200 else "down"
    except Exception:
        checks["tts"] = "down"

    try:
        from app.core.mqtt_server import get_mqtt_manager
        mgr = get_mqtt_manager()
        checks["mqtt_devices"] = len(mgr.sessions)
    except Exception:
        checks["mqtt_devices"] = 0

    # Intent info
    try:
        if config.intent_provider == "intent_llm":
            checks["intent_mode"] = "intent_llm"
            checks["intent_model"] = config.intent_model
            checks["intent_fallback"] = config._get(
                "intent", "fallback_model", default=None
            )
        else:
            checks["intent_mode"] = config.intent_provider
    except Exception:
        pass

    if any(v == "down" for v in checks.values()):
        checks["status"] = "degraded"
    return checks


@app.get("/")
async def root():
    return RedirectResponse(url="/chat")

"""FastAPI app — Xiaozhi CE v2."""
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.core.logger import setup_logging, cleanup_old_logs, shutdown_logging
setup_logging()

try:
    import app.core.error_sanitizer as _error_sanitizer
    _error_sanitizer.install()
    import app.core.config_validator as _config_validator
    _config_validator.validate_or_warn()
except Exception as _err:
    sys.stderr.write(f"⚠ Safety features install failed: {_err}\n")

from app.core.signal_handler import install as install_signal_handler
install_signal_handler()
from app.config import config
from app.database import init_db, AsyncSessionLocal
from app.repositories import chat as chat_repo
from app.core.mqtt_server import get_mqtt_manager
from app.routes import web_ui as web, chat_ws, api as audio_api, esp32_ws, device_sync_ws
from app.core.api import ota_handler
from app.core.tunnel_service import TunnelService
from app.core.runtime import initialize_runtime, close_runtime
from app.core.warmup import (
    warmup_llm,
    warmup_tts,
    warmup_asr,
    warmup_denoiser,
    warmup_intent_model,
    unload_local_llm_models,
)
from app.tasks.background import (
    cleanup_stale_sessions_loop,
    poll_sensors_loop,
)

tunnel_service = TunnelService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Khởi động server...")
    logger.info(f"🔧 Event loop: {type(asyncio.get_running_loop()).__name__}")
    logger.info(
        f"📦 Source: {os.path.abspath(__file__)} | "
        f"Config: {os.path.abspath('config.yaml')}"
    )

    deleted_logs = cleanup_old_logs()
    if deleted_logs:
        logger.info(f"🧹 Xóa {deleted_logs} log cũ")

    await init_db()
    logger.info("✅ Database sẵn sàng")
    app.state.runtime = initialize_runtime(logger)
    logger.info("✅ Shared providers sẵn sàng")

    try:
        async with AsyncSessionLocal() as db:
            deleted = await chat_repo.cleanup_old_sessions(
                db, days=config.session_cleanup_days,
            )
            if deleted:
                logger.info(f"🧹 Xóa {deleted} session cũ")
    except Exception as e:
        logger.warning(f"⚠️ Cleanup session lỗi: {e}")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                warmup_llm(), warmup_tts(), warmup_asr(), warmup_denoiser(),
                return_exceptions=True,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("⚠️ Warmup timeout 120s — bỏ qua")

    mqtt_mgr = get_mqtt_manager()
    await mqtt_mgr.start()

    _cleanup_task = asyncio.create_task(cleanup_stale_sessions_loop())
    _poll_task = asyncio.create_task(poll_sensors_loop())

    # Real-time engines (reminder & cleanup)
    try:
        from app.core.reminder_engine import get_engine as _re
        from app.core.cleanup_engine import get_engine as _ce
        _rem_engine = _re()
        _clean_engine = _ce()
        _rem_engine.interval = 1
        _clean_engine.interval = int(config._get('calendar', 'cleanup_interval_sec', default=3600))
        _clean_engine.rem_days = int(config._get('calendar', 'reminder_retention_days', default=7))
        _clean_engine.ev_days = int(config._get('calendar', 'event_retention_days', default=30))
        _clean_engine.music_dir = Path(config._get('music', 'cache_dir', default='data/music_cache'))
        _clean_engine.music_max_bytes = int(config._get('music', 'cache_max_mb', default=500)) * 1024 * 1024
        await _rem_engine.start()
        await _clean_engine.start()
        app.state.reminder_engine = _rem_engine
        app.state.cleanup_engine = _clean_engine
        logger.info('Real-time engines started')
    except Exception as _e:
        logger.warning(f'Real-time engines start failed: {_e}')

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
                    _interval = config._get("lamp_automation", "check_interval_sec", default=30)
                    _sched.add_job(
                        check_rules, "interval",
                        seconds=_interval, id="automation_tick",
                    )
                    logger.info(f"Automation rules: mỗi {_interval}s")
                except Exception as e:
                    logger.warning(f"Automation rules lỗi: {e}")
            else:
                logger.warning("Scheduler disabled - cài: pip install apscheduler")
    except Exception as e:
        logger.warning(f"Scheduler setup lỗi: {e}")

    # Adaptive lighting
    try:
        _la_cfg = config._get("lamp_automation", default={}) or {}
        if _la_cfg.get("adaptive_lighting", True):
            from app.core.automation import apply_time_profile

            async def _apply_adaptive_later():
                await asyncio.sleep(5.0)
                await apply_time_profile(logger)

            asyncio.create_task(_apply_adaptive_later())
            logger.info("Adaptive lighting: sẽ áp dụng sau 5s")
    except Exception as e:
        logger.warning(f"Adaptive lighting setup lỗi: {e}")

    async def _start_tunnel_bg():
        try:
            tunnel_ok = await tunnel_service.start()
            if tunnel_ok:
                logger.info(f"🌐 Public URL: {tunnel_service.get_public_url()}")
            elif config.tunnel_enabled:
                logger.warning("⚠️ Tunnel không start được — server vẫn chạy local")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(f"⚠️ Tunnel start lỗi: {exc}")

    _tunnel_task = asyncio.create_task(_start_tunnel_bg())

    # Warmup intent model CHỈ KHI provider là intent_llm
    if config.intent_provider == "intent_llm":
        _intent_warmup_task = asyncio.create_task(warmup_intent_model())
        logger.info("🔥 Warmup intent model sẽ chạy...")
    else:
        _intent_warmup_task = None
        logger.info(f"⏭️ Bỏ qua warmup intent (provider={config.intent_provider})")

    logger.info(f"🌐 Mở http://localhost:{config.port}/chat")
    yield

    # Hủy các background tasks khi tắt server (an toàn với None)
    for t in (_cleanup_task, _poll_task, _intent_warmup_task, _tunnel_task):
        if t is not None:
            t.cancel()

    if _sched is not None:
        try:
            _sched.shutdown()
        except Exception:
            pass
    try:
        await tunnel_service.stop()
    except Exception as e:
        logger.warning(f"⚠️ Stop tunnel: {e}")

    try:
        if hasattr(app.state, 'reminder_engine'):
            await app.state.reminder_engine.stop()
        if hasattr(app.state, 'cleanup_engine'):
            await app.state.cleanup_engine.stop()
    except Exception:
        pass

    await mqtt_mgr.stop()
    await unload_local_llm_models()
    try:
        from app.core.providers.tts.vieneu import close_vieneu_client
        await close_vieneu_client()
    except Exception as e:
        logger.warning(f"⚠️ Stop TTS client lỗi: {e}")
    await close_runtime()
    app.state.runtime = None
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


@app.middleware("http")
async def request_metrics(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    logger.debug(
        f"HTTP {request.method} {request.url.path} "
        f"{response.status_code} {elapsed * 1000:.0f}ms"
    )
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(web.router)
app.include_router(chat_ws.router)
app.include_router(audio_api.router)
app.include_router(esp32_ws.router)
app.include_router(device_sync_ws.router)
app.include_router(ota_handler.router)

try:
    from app.routes.api import router as _cal_router
    app.include_router(_cal_router)
except ImportError:
    pass


@app.get("/health")
async def health():
    """Health check chi tiết - kiểm tra LLM, ASR, TTS, MQTT."""
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
        mgr = get_mqtt_manager()
        checks["mqtt_devices"] = len(mgr.sessions)
    except Exception:
        checks["mqtt_devices"] = 0

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
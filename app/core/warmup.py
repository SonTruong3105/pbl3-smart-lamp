"""Model warmup and memory management routines."""
import asyncio
import os
import httpx
from loguru import logger

from app.config import config


async def warmup_llm():
    logger.info("🔥 Warmup LLM (Smart Router)...")
    llm_cfg = config.llm_config

    async def _warmup_one(name):
        if name not in llm_cfg:
            return
        pcfg = llm_cfg[name]
        if not pcfg or pcfg.get("type") == "openai_compatible":
            return

        model = pcfg.get("model", "unknown")
        url = pcfg.get("url", "http://localhost:11434/api/chat")

        sys_prompt = (config.system_prompt or "").replace(
            "{{current_time}}", "00:00 01/01/2026"
        )
        warmup_msgs = []
        if sys_prompt:
            warmup_msgs.append({"role": "system", "content": sys_prompt})
        warmup_msgs += [
            {"role": "user", "content": "Chào bạn"},
            {"role": "assistant", "content": "Dạ em đây!"},
            {"role": "user", "content": "Hôm nay thế nào"},
            {"role": "assistant", "content": "Mình ổn, cảm ơn bạn!"},
            {"role": "user", "content": "hehe"},
            {"role": "assistant", "content": "Hihi!"},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "Vâng ạ."},
            {"role": "user", "content": "Xin chào"},
        ]

        opts = {
            "num_predict": 1,
            "num_keep": int(pcfg.get("num_keep", 500)),
            "num_ctx": int(pcfg.get("num_ctx", 2048)),
        }
        if pcfg.get("num_batch") is not None:
            opts["num_batch"] = int(pcfg["num_batch"])
        if pcfg.get("num_keep") is not None:
            opts["num_keep"] = int(pcfg["num_keep"])
        if pcfg.get("num_gpu") is not None:
            opts["num_gpu"] = int(pcfg["num_gpu"])

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(
                    url,
                    json={
                        "model": model,
                        "messages": warmup_msgs,
                        "stream": False,
                        "keep_alive": pcfg.get("keep_alive", -1),
                        "options": opts,
                    },
                )
                if r.status_code == 404:
                    logger.warning(f"⚠️ Model '{model}' chưa pull (404)")
                    return
                r.raise_for_status()
            logger.info(
                f"✅ Warmup OK: {name} ({model}) — "
                f"prompt preloaded (sys={len(sys_prompt)}b, num_keep={opts['num_keep']})"
            )
        except Exception as e:
            logger.warning(f"⚠️ Warmup {name} lỗi: {e}")

    await asyncio.gather(
        _warmup_one("ollama_chat"),
        return_exceptions=True
    )


async def unload_local_llm_models():
    """Release Ollama models from RAM/VRAM while leaving the Ollama service alive."""
    llm_cfg = config.llm_config
    names = ("ollama_chat", "ollama_tools")

    async def _unload_one(name):
        pcfg = llm_cfg.get(name) or {}
        if not pcfg or pcfg.get("type") == "openai_compatible":
            return
        model = pcfg.get("model")
        url = pcfg.get("url", "http://127.0.0.1:11434/api/chat")
        if not model:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": model,
                        "messages": [],
                        "stream": False,
                        "keep_alive": 0,
                    },
                )
                response.raise_for_status()
            logger.info(f"🧹 Đã giải phóng Ollama model: {model}")
        except Exception as e:
            logger.warning(f"⚠️ Không giải phóng được Ollama model '{model}': {e}")

    await asyncio.gather(*(_unload_one(name) for name in names))


async def warmup_tts():
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


async def warmup_asr():
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


async def warmup_intent_model():
    try:
        await asyncio.sleep(2)
        logger.info("🔥 Warmup intent model...")
        intent_cfg = config._get("intent", default={}) or {}
        url = intent_cfg.get("url")
        model = intent_cfg.get("model")
        if not url or not model:
            logger.info("⏭️ Bỏ qua warmup intent (chưa cấu hình)")
            return
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "keep_alive": intent_cfg.get("keep_alive", -1),
            "options": {
                "num_predict": 1,
                "num_ctx": intent_cfg.get("num_ctx", 1024),
                "num_batch": intent_cfg.get("num_batch", 128),
                "num_gpu": intent_cfg.get("num_gpu", 99),
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(url, json=payload)
        logger.info(f"✅ Intent warmup OK: {model}")
    except Exception as e:
        logger.error(f"❌ Intent warmup error: {e}")

"""Shared process-level providers and runtime resources."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import config
from app.core.providers.base import ProviderRegistry
from app.core.providers.asr import phowhisper  # noqa: F401
from app.core.providers.llm import ollama  # noqa: F401
from app.core.providers.llm import openai_compatible  # noqa: F401
from app.core.providers.llm import hybrid_provider  # noqa: F401
from app.core.providers.tts import edge, piper, vieneu  # noqa: F401
from app.core.providers.tools.registry import TOOLS_SCHEMA
from app.core.providers.tools.unified import UnifiedToolHandler


@dataclass
class RuntimeProviders:
    asr: object
    llm: object
    tts: object
    tool_handler: object


_runtime: Optional[RuntimeProviders] = None


def initialize_runtime(log=None) -> RuntimeProviders:
    global _runtime
    if _runtime is not None:
        return _runtime

    _runtime = RuntimeProviders(
        asr=ProviderRegistry.create_asr(
            config.asr_provider,
            config={
                "url": config.asr_url,
                "model": config.asr_model,
                "language": config.asr_language,
                "request_timeout": config.asr_request_timeout,
            },
            log=log,
        ),
        llm=ProviderRegistry.create_llm(
            config.llm_provider,
            config={
                "url": config.llm_url,
                "model": config.llm_model,
                "temperature": config.llm_temperature,
                "num_predict": config.llm_num_predict,
                "max_tool_iterations": config.llm_max_tool_iterations,
                "request_timeout": config.llm_request_timeout,
                "think": config.llm_think,
                "num_ctx": config.llm_num_ctx,
                "num_batch": config.llm_num_batch,
                "keep_alive": config.llm_keep_alive,
            },
            tools_schema=TOOLS_SCHEMA,
            log=log,
        ),
        tts=ProviderRegistry.create_tts(
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
            log=log,
        ),
        tool_handler=UnifiedToolHandler(log=log),
    )
    return _runtime


def get_runtime() -> Optional[RuntimeProviders]:
    return _runtime


async def close_runtime() -> None:
    global _runtime
    if _runtime is None:
        return
    try:
        close_asr = getattr(_runtime.asr, "close", None)
        if close_asr is not None:
            result = close_asr()
            if hasattr(result, "__await__"):
                await result
        else:
            from app.core.providers.asr.phowhisper import close_asr_client
            await close_asr_client()
    finally:
        try:
            close_tts = getattr(_runtime.tts, "close", None)
            if close_tts is not None:
                result = close_tts()
                if hasattr(result, "__await__"):
                    await result
        finally:
            _runtime = None

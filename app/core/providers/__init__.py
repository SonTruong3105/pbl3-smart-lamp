from app.core.providers.base import ProviderRegistry
from app.core.providers.asr import phowhisper
from app.core.providers.llm import ollama, openai_compatible, hybrid_provider
from app.core.providers.tts import edge, piper, vieneu
from app.core.providers.memory import local, none, mem_local_short

__all__ = ["ProviderRegistry"]

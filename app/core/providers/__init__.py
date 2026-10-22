from app.core.providers.base import ProviderRegistry
from app.core.providers.asr import phowhisper  # noqa
from app.core.providers.llm import ollama      # noqa
from app.core.providers.tts import edge, piper , vieneu  # noqa
from app.core.providers.memory import local, none  # noqa

__all__ = ["ProviderRegistry"]
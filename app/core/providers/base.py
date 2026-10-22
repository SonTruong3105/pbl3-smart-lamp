"""Base classes cho providers."""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, List
from loguru import logger


class ASRProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        ...


class LLMProviderBase(ABC):
    def __init__(self, config: dict, tools_schema: list = None, log=None):
        self.config = config
        self.tools_schema = tools_schema or []
        self.log = log or logger

    @abstractmethod
    async def chat_stream(self, messages, tools=None) -> AsyncGenerator[dict, None]:
        ...


class TTSProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def synthesize(self, text: str, **kwargs) -> bytes:
        ...


class MemoryProviderBase(ABC):
    def __init__(self, config: dict, log=None):
        self.config = config
        self.log = log or logger

    @abstractmethod
    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        ...

    @abstractmethod
    async def save(self, session_id: str, messages: List[dict]) -> None:
        ...


class ProviderRegistry:
    _ASR = {}
    _LLM = {}
    _TTS = {}
    _MEMORY = {}

    @classmethod
    def register_asr(cls, name, provider_cls):
        cls._ASR[name] = provider_cls

    @classmethod
    def register_llm(cls, name, provider_cls):
        cls._LLM[name] = provider_cls

    @classmethod
    def register_tts(cls, name, provider_cls):
        cls._TTS[name] = provider_cls

    @classmethod
    def register_memory(cls, name, provider_cls):
        cls._MEMORY[name] = provider_cls

    @classmethod
    def create_asr(cls, name, **kwargs):
        p = cls._ASR.get(name)
        if not p:
            raise ValueError(f"ASR provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_llm(cls, name, **kwargs):
        p = cls._LLM.get(name)
        if not p:
            raise ValueError(f"LLM provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_tts(cls, name, **kwargs):
        p = cls._TTS.get(name)
        if not p:
            raise ValueError(f"TTS provider '{name}' không tồn tại")
        return p(**kwargs)

    @classmethod
    def create_memory(cls, name, **kwargs):
        p = cls._MEMORY.get(name)
        if not p:
            raise ValueError(f"Memory provider '{name}' không tồn tại")
        return p(**kwargs)
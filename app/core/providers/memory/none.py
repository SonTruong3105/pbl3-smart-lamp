"""No memory provider."""
from typing import List, Optional
from app.core.providers.base import MemoryProviderBase, ProviderRegistry


class NoMemoryProvider(MemoryProviderBase):
    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        return None

    async def save(self, session_id: str, messages: List[dict]) -> None:
        return None


ProviderRegistry.register_memory("none", NoMemoryProvider)
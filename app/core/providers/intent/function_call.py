"""FunctionCallIntentProvider — chế độ mặc định, để LLM tự gọi tool."""
from typing import Any, Optional

from app.core.providers.intent.base import IntentProviderBase


class FunctionCallIntentProvider(IntentProviderBase):
    async def detect_intent(self, conn: Any, text: str) -> Optional[str]:
        return None  # Không can thiệp, để LLM native tool calling


class NoIntentProvider(IntentProviderBase):
    """Bỏ qua intent, chat thuần."""
    async def detect_intent(self, conn: Any, text: str) -> Optional[str]:
        return None

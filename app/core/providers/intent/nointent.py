"""NoIntentProvider — bỏ qua intent, chat thuần."""
from typing import Any, Optional

from app.core.providers.intent.base import IntentProviderBase


class NoIntentProvider(IntentProviderBase):
    async def detect_intent(self, conn: Any, text: str) -> Optional[str]:
        return None

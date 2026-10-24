"""IntentProviderBase — interface cho các intent provider."""
from abc import ABC, abstractmethod
from typing import Any, Optional


class IntentProviderBase(ABC):
    @abstractmethod
    async def detect_intent(
        self, conn: Any, text: str
    ) -> Optional[str]:
        """Trả về tên tool nếu phát hiện intent, ngược lại None."""
        ...

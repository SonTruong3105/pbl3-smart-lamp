"""Local memory provider — RAM."""
from typing import Dict, List, Optional
from collections import deque
from app.core.providers.base import MemoryProviderBase, ProviderRegistry


class LocalMemoryProvider(MemoryProviderBase):
    def __init__(self, config: dict, log=None):
        super().__init__(config, log)
        self._store: Dict[str, deque] = {}
        self.max_turns = config.get("max_turns", 20)

    def _get_deque(self, session_id: str) -> deque:
        if session_id not in self._store:
            self._store[session_id] = deque(maxlen=self.max_turns)
        return self._store[session_id]

    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        dq = self._store.get(session_id)
        if not dq:
            return None
        lines = [f"- {item}" for item in dq if item]
        return "\n".join(lines) if lines else None

    async def save(self, session_id: str, messages: List[dict]) -> None:
        dq = self._get_deque(session_id)
        for msg in messages:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if not content or role == "system":
                continue
            if role in ("user", "assistant"):
                dq.append(f"[{role}] {content[:120]}")

    def clear(self, session_id: str):
        self._store.pop(session_id, None)


ProviderRegistry.register_memory("local", LocalMemoryProvider)
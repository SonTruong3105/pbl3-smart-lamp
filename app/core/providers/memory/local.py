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

# ===== Gộp từ mem_local_short.py =====
"""MemLocalShortProvider — tóm tắt hội thoại bằng LLM và lưu file YAML."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from app.core.providers.base import MemoryProviderBase, ProviderRegistry

MEMORY_FILE = Path("data/.memory.yaml")

SUMMARY_PROMPT = """Tóm tắt hội thoại sau thành JSON có 2 phần:
- spatiotemporal_archive: thời gian, địa điểm, sự kiện
- identity_map: danh tính, sở thích, mối quan hệ
Chỉ trả về JSON, không giải thích.
Hội thoại:
{conversation}"""


class MemLocalShortProvider(MemoryProviderBase):
    def __init__(self, config: dict, log=None):
        super().__init__(config, log)
        self._data: Dict[str, dict] = {}
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        if MEMORY_FILE.exists():
            try:
                self._data = yaml.safe_load(MEMORY_FILE.read_text(encoding="utf-8")) or {}
            except Exception as e:
                self.log.warning(f"Không đọc được memory: {e}")

    def _save(self):
        try:
            MEMORY_FILE.write_text(
                yaml.dump(self._data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as e:
            self.log.warning(f"Không ghi được memory: {e}")

    async def get_context(self, session_id: str, query: str = None) -> Optional[str]:
        mem = self._data.get(str(session_id))
        if not mem:
            return None
        lines = []
        for section, val in mem.items():
            if isinstance(val, dict):
                lines.append(f"[{section}]")
                for k, v in val.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"[{section}] {val}")
        return "\n".join(lines)

    async def save(self, session_id: str, messages: List[dict]) -> None:
        if len(messages) < 5:
            return
        conversation = "\n".join(
            f"{m.get('role')}: {m.get('content','')}" for m in messages
        )
        try:
            from app.core.providers.base import ProviderRegistry
            from app.config import config
            llm = ProviderRegistry.create_llm(
                config.llm_provider,
                config={
                    "url": config.llm_url,
                    "model": config.llm_model,
                    "temperature": 0.1,
                    "num_predict": 512,
                    "request_timeout": 60.0,
                },
            )
            text = ""
            async for ev in llm.response_with_functions(
                [{"role": "user", "content": SUMMARY_PROMPT.format(conversation=conversation)}]
            ):
                if ev["type"] == "token":
                    text += ev["content"]
            start, end = text.find("{"), text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
            else:
                data = {"raw": text}
            self._data[str(session_id)] = data
            self._save()
        except Exception as e:
            self.log.warning(f"Tóm tắt memory lỗi: {e}")


ProviderRegistry.register_memory("mem_local_short", MemLocalShortProvider)

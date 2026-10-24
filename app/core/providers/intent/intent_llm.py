"""IntentLLMProvider — phân loại intent bằng LLM nhỏ trên CPU.

Chiến lược:
- Dùng qwen3.5:0.8b (rất nhẹ) để phân loại nhanh
- Nếu không chắc (chat/không rõ) → trả None
  → Main LLM xử lý qua function_call (fallback tự động)
- Nếu 0.8b fail → thử fallback model (vd: 2b đã có sẵn)
- Cache LRU để tránh gọi lại
"""
import hashlib
from collections import OrderedDict
from typing import Any, Optional

import httpx
from loguru import logger

from app.config import config
from app.core.providers.intent.base import IntentProviderBase

INTENT_TOOL_MAP = {
    "weather": "get_weather",
    "forecast": "get_forecast",
    "time": "get_current_time",
    "weekday": "get_weekday",
    "date_diff": "days_between",
    "search": "web_search",
    "chat": None,
}

# Prompt tối ưu cho model nhỏ — ngắn nhưng có ví dụ
INTENT_PROMPT = """Phân loại câu hỏi vào ĐÚNG 1 trong 7 nhãn:
weather, forecast, time, weekday, date_diff, search, chat

Định nghĩa:
- weather: hỏi thời tiết hiện tại (VD: "thời tiết Hà Nội")
- forecast: hỏi dự báo nhiều ngày (VD: "dự báo 3 ngày tới")
- time: hỏi giờ hiện tại (VD: "mấy giờ rồi")
- weekday: hỏi thứ trong tuần (VD: "ngày mai thứ mấy")
- date_diff: tính số ngày (VD: "còn mấy ngày đến Tết")
- search: tìm thông tin web (VD: "giá vàng hôm nay")
- chat: chào hỏi, tán gẫu (VD: "xin chào")

Chỉ trả về 1 nhãn duy nhất, không giải thích.

Câu hỏi: {text}
Nhãn:"""


class IntentLLMProvider(IntentProviderBase):
    def __init__(self, log=None):
        self.log = log or logger

        self.url = config.intent_url
        self.model = config.intent_model
        self.fallback_model = config._get(
            "intent", "fallback_model", default=None
        )
        self.timeout = config.intent_timeout
        self.temperature = config._get("intent", "temperature", default=0.0)
        self.num_predict = config._get("intent", "num_predict", default=5)
        cache_size = config._get("intent", "cache_size", default=500)

        self._cache: OrderedDict[str, Optional[str]] = OrderedDict()
        self._cache_size = max(10, int(cache_size))
        self._stats = {"hit": 0, "miss": 0, "error": 0, "fallback": 0}

        self.log.info(
            f"🧠 IntentLLM init | model={self.model} "
            f"fallback={self.fallback_model} timeout={self.timeout}s"
        )

    def _cache_key(self, device_id: str, text: str) -> str:
        return hashlib.md5(f"{device_id}:{text}".encode()).hexdigest()

    def _cache_get(self, key: str) -> tuple[bool, Optional[str]]:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._stats["hit"] += 1
            return True, self._cache[key]
        self._stats["miss"] += 1
        return False, None

    def _cache_put(self, key: str, value: Optional[str]):
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def detect_intent(self, conn: Any, text: str) -> Optional[str]:
        device_id = getattr(conn, "device_id", "unknown")
        cache_key = self._cache_key(device_id, text)

        hit, cached_tool = self._cache_get(cache_key)
        if hit:
            self.log.debug(f"🧠 IntentLLM cache HIT: {text[:30]!r} → {cached_tool}")
            return cached_tool

        intent = await self._classify(text)
        tool = INTENT_TOOL_MAP.get(intent)

        if tool is None:
            self._cache_put(cache_key, None)
            self.log.debug(
                f"🧠 IntentLLM → chat (fallback to function_call)"
            )
            return None

        self._cache_put(cache_key, tool)
        self.log.info(f"🧠 IntentLLM → {intent} → {tool}")
        return tool

    async def _classify(self, text: str) -> str:
        # Primary model (0.8b)
        try:
            result = await self._call_llm(self.model, text)
            if result:
                return result
        except Exception as e:
            self.log.warning(f"⚠️ IntentLLM primary ({self.model}) lỗi: {e}")
            self._stats["error"] += 1

        # Fallback model (2b-q4_K_M)
        if self.fallback_model:
            try:
                result = await self._call_llm(self.fallback_model, text)
                if result:
                    self._stats["fallback"] += 1
                    self.log.info(
                        f"🔁 IntentLLM fallback ({self.fallback_model}): {result}"
                    )
                    return result
            except Exception as e:
                self.log.warning(
                    f"⚠️ IntentLLM fallback ({self.fallback_model}) lỗi: {e}"
                )

        return "chat"

    async def _call_llm(self, model: str, text: str) -> Optional[str]:
        prompt = INTENT_PROMPT.format(text=text)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self.url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.num_predict,
                    },
                },
            )
            r.raise_for_status()
            data = r.json()
            raw = (data.get("message", {}).get("content") or "").strip().lower()

        # Parse intent keyword từ raw
        for intent in INTENT_TOOL_MAP.keys():
            if intent in raw:
                return intent

        self.log.debug(f"⚠️ IntentLLM response không rõ: {raw[:50]!r}")
        return "chat"

    def get_stats(self) -> dict:
        total = self._stats["hit"] + self._stats["miss"]
        hit_rate = self._stats["hit"] / total * 100 if total > 0 else 0
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "hit_rate_percent": round(hit_rate, 1),
        }

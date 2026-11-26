"""IntentLLMProvider — Qwen3.5-0.8B (CPU) phân loại intent.

Trả về structured IntentResult:
- tool = None → chat thuần
- needs_args=False → chạy tool trực tiếp (không cần LLM extract)
- needs_args=True  → để main LLM extract args qua native tool calling
"""
import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger

from app.config import config
from app.core.providers.intent.base import IntentProviderBase


@dataclass
class IntentResult:
    intent: str
    tool: Optional[str]
    needs_args: bool


INTENT_DEFINITIONS = {
    "weather": ("weather", True),
    "device":  ("device", True),
    "knowledge": ("knowledge", True),
    "calendar": ("list_calendar", True),
    "chat": (None, False),
}

INTENT_PROMPT = """Phân loại câu sau vào ĐÚNG 1 trong 5 nhãn: weather, device, knowledge, calendar, chat.
CHỈ TRẢ VỀ 1 TỪ DUY NHẤT. KHÔNG GIẢI THÍCH.

Quy tắc:
- weather: thời tiết, nhiệt độ, mưa, nắng, dự báo
- device: bật/tắt đèn, độ sáng, màu đèn, cảm biến phòng
- knowledge: tin tức, tỷ giá, giá vàng, chứng khoán, tính toán, tra cứu
- calendar: xem lịch, lịch hôm nay, lịch ngày mai, thêm/sửa/xóa lịch, lịch thi
- chat: chào hỏi, tán gẫu, cảm ơn, câu trả lời phủ định/từ chối ngắn, các câu còn lại

Ví dụ:
"nhiệt độ đà nẵng" -> weather
"ngày mai có mưa không" -> weather
"bật đèn lên" -> device
"chỉnh đèn màu vàng" -> device
"giá vàng hôm nay" -> knowledge
"tỷ giá đô la" -> knowledge
"lịch học hôm nay" -> calendar
"không có" -> chat
"không cần đâu" -> chat
"chào đèn" -> chat
"bạn khỏe không" -> chat

Câu cần phân loại: "{text}"
Nhãn:"""

_SHORT_NEGATIVE_RE = re.compile(
    r"^(không|ko|k|không có|ko có|k có|không cần|ko cần|thôi|đừng|chưa|chưa có|vậy thôi|không sao|ừ|ờ|ok|okay)[\s.!?…]*$",
    re.IGNORECASE,
)

_CALENDAR_HINT_RE = re.compile(
    r"\b(lịch|sự kiện|cuộc hẹn|hẹn|thi|kiểm tra|nhắc|deadline|hôm nay|ngày mai|tuần|tháng|thứ\s*[2-7]|chủ nhật|\d{1,2}[:h]\d{0,2})\b",
    re.IGNORECASE,
)


def _is_short_negative_or_ack(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_SHORT_NEGATIVE_RE.match(t) and not _CALENDAR_HINT_RE.search(t))


class IntentLLMProvider(IntentProviderBase):
    def __init__(self, log=None):
        self.log = log or logger
        self.url = config.intent_url
        self.model = config.intent_model
        self.fallback_model = config._get("intent", "fallback_model", default=None)
        self.timeout = config.intent_timeout
        self.temperature = config._get("intent", "temperature", default=0.0)
        self.num_predict = config._get("intent", "num_predict", default=100)
        cache_size = config._get("intent", "cache_size", default=500)
        self.num_gpu = config._get("intent", "num_gpu", default=0)
        self.num_ctx = config._get("intent", "num_ctx", default=2048)
        self.num_batch = config._get("intent", "num_batch", default=128)
        self.keep_alive = config._get("intent", "keep_alive", default="30m")
        self._cache: OrderedDict[str, Optional[IntentResult]] = OrderedDict()
        self._cache_size = max(10, int(cache_size))
        self._stats = {"hit": 0, "miss": 0, "error": 0, "fallback": 0}
        self.log.info(f"🧠 IntentLLM init | model={self.model} fallback={self.fallback_model} num_gpu={self.num_gpu}")

    def _cache_key(self, device_id, text):
        return hashlib.md5(f"{device_id}:{text}".encode()).hexdigest()

    def _cache_get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key); self._stats["hit"] += 1
            return True, self._cache[key]
        self._stats["miss"] += 1
        return False, None

    def _cache_put(self, key, value):
        self._cache[key] = value; self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def detect_intent(self, conn: Any, text: str) -> Optional[str]:
        r = await self.detect_intent_full(conn, text)
        if r and r.tool and not r.needs_args:
            return r.tool
        return None

    async def detect_intent_full(self, conn: Any, text: str) -> Optional[IntentResult]:
        # ═══ RULE-BASED GUARDRAIL (substring — không regex) ═══
        text_lower = text.lower()

        # Hard guard before intent cache/model: negated lamp requests must never
        # be classified as an executable device intent.
        from app.core.routing.fast_track import NEGATED_DEVICE_RE
        if NEGATED_DEVICE_RE.search(text_lower):
            return IntentResult("chat", None, False)

        # Short negative / acknowledgment without calendar hints goes straight to chat.
        if _is_short_negative_or_ack(text):
            self.log.debug(f"🧠 Guardrail: short negative/ack → chat: {text[:30]!r}")
            return IntentResult("chat", None, False)

        # Route explicit calendar requests before the classifier can collapse them
        # into generic chat (or reuse a cached chat label for the same utterance).
        calendar_triggers = (
            "lịch", "lịch trình", "lịch hẹn", "lịch học", "lịch làm việc",
            "xem lịch", "đọc lịch", "thêm lịch", "tạo lịch", "đặt lịch",
            "sửa lịch", "đổi lịch", "cập nhật lịch", "xóa lịch", "hủy lịch", "huỷ lịch",
        )
        if any(trigger in text_lower for trigger in calendar_triggers) and not any(
            trigger in text_lower for trigger in ("âm lịch", "dương lịch")
        ):
            self.log.debug("🧠 Guardrail: calendar")
            return IntentResult("calendar", "list_calendar", True)

        # Explicit lamp controls go through the dedicated lamp tools.
        _lamp_control_triggers = [
            "bật đèn", "mở đèn", "tắt đèn", "đóng đèn",
            "độ sáng đèn", "chỉnh sáng", "tăng sáng", "giảm sáng",
            "màu đèn", "chế độ đèn", "đổi màu", "chuyển màu",
            "nhiệt độ màu", "nhiệt màu", "ánh sáng trắng", "trắng sáng", "màu trắng",
            "ánh sáng vàng", "màu vàng", "ánh sáng ấm", "màu ấm", "trung tính", "kelvin",
        ]
        if any(t in text_lower for t in _lamp_control_triggers):
            self.log.debug("🧠 Guardrail: lamp control")
            return IntentResult("device", None, False)

        # Room environment readings are server wrappers around MCP + DeviceHub.
        _air_quality_triggers = ["chất lượng không khí", "không khí trong phòng", "bụi mịn", "pm2", "pm25"]
        if any(t in text_lower for t in _air_quality_triggers):
            self.log.debug("🧠 Guardrail: air quality -> get_air_quality")
            return IntentResult("device", "get_air_quality", False)

        _sensor_triggers = [
            "nhiệt độ phòng", "độ ẩm", "ẩm độ", "ánh sáng", "cảm biến",
            "có ai", "có người", "hiện diện", "lux",
        ]
        if any(t in text_lower for t in _sensor_triggers):
            self.log.debug("🧠 Guardrail: room sensor -> get_sensor")
            return IntentResult("device", "get_sensor", True)

        # Knowledge
        _kn_triggers = ["giá vàng", "chứng khoán", "tỷ giá", "đô la", "usd", "bitcoin", "tin tức"]
        if any(t in text_lower for t in _kn_triggers):
            self.log.debug("🧠 Guardrail: knowledge")
            return IntentResult("knowledge", "web_search", True)

        # Weather (ngoài trời)
        _weather_triggers = ["thời tiết", "dự báo", "mưa", "nắng"]
        if any(t in text_lower for t in _weather_triggers):
            self.log.debug("🧠 Guardrail: weather")
            return IntentResult("weather", "web_search", True)

        # Time
        _time_triggers = ["mấy giờ", "giờ rồi", "hôm nay thứ", "ngày mấy"]
        if any(t in text_lower for t in _time_triggers):
            self.log.debug("🧠 Guardrail: time")
            return IntentResult("time", "get_current_time", False)

        device_id = getattr(conn, "device_id", "unknown")
        cache_key = self._cache_key(device_id, text)
        hit, cached = self._cache_get(cache_key)
        if hit:
            self.log.debug(f"🧠 Intent cache HIT: {text[:30]!r} → {cached}")
            return cached
        label = await self._classify(text)
        result = self._build_result(label)
        self._cache_put(cache_key, result)
        if result and result.intent != "chat":
            self.log.info(f"🧠 Intent: {text[:40]!r} → {result.intent} → {result.tool} (args={result.needs_args})")
        else:
            self.log.debug(f"🧠 Intent: {text[:40]!r} → chat")
        return result

    def _build_result(self, label):
        if label not in INTENT_DEFINITIONS:
            return IntentResult("chat", None, False)
        tool, needs_args = INTENT_DEFINITIONS[label]
        return IntentResult(label, tool, needs_args)

    async def _classify(self, text):
        try:
            r = await self._call_llm(self.model, text)
            if r: return r
        except Exception as e:
            self.log.warning(f"⚠️ Intent primary ({self.model}) lỗi: {e}")
            self._stats["error"] += 1
        if self.fallback_model:
            try:
                r = await self._call_llm(self.fallback_model, text)
                if r:
                    self._stats["fallback"] += 1
                    self.log.info(f"🔁 Intent fallback ({self.fallback_model}): {r}")
                    return r
            except Exception as e:
                self.log.warning(f"⚠️ Intent fallback ({self.fallback_model}) lỗi: {e}")
        return "chat"

    async def _call_llm(self, model, text):
        prompt = INTENT_PROMPT.format(text=text)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False, "think": False, "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature, "num_predict": self.num_predict,
                "num_ctx": self.num_ctx, "num_batch": self.num_batch, "num_gpu": self.num_gpu,
                "stop": ["\n", ".", ",", "\t"],
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(self.url, json=payload); r.raise_for_status()
            data = r.json()
            raw = (data.get("message", {}).get("content") or "").strip().lower()
        head = raw.strip().split("\n", 1)[0]
        first_word = head.strip(' .,;:!?\"\'`*#[]()').lower()
        if first_word in INTENT_DEFINITIONS:
            return first_word

        for intent in INTENT_DEFINITIONS.keys():
            if re.search(rf"\b{re.escape(intent)}\b", raw, re.IGNORECASE):
                return intent

        raw_clean = raw.replace("_", "").replace("-", "").replace(" ", "")
        for intent in INTENT_DEFINITIONS.keys():
            if intent.replace("_", "").replace("-", "") in raw_clean:
                return intent

        self.log.debug(f"⚠️ Intent response không rõ: {raw[:80]!r}")
        return "chat"

    def get_stats(self):
        total = self._stats["hit"] + self._stats["miss"]
        hit_rate = self._stats["hit"] / total * 100 if total > 0 else 0
        return {**self._stats, "cache_size": len(self._cache), "hit_rate_percent": round(hit_rate, 1)}
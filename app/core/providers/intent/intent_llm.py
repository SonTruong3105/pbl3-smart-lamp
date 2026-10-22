"""
Intent Recognition — 3 modes: function_call | intent_llm | nointent

- function_call: LLM tự gọi tool (đang dùng)
- intent_llm:    Pre-classify bằng LLM nhỏ trước main LLM
- nointent:      Không dùng tools, chat thuần
"""
import json
import httpx
from typing import Optional
from loguru import logger

from app.config import config


# Danh sách intent hỗ trợ + tool tương ứng
INTENT_TOOL_MAP = {
    "weather":  "get_weather",
    "forecast": "get_forecast",
    "time":     "get_current_time",
    "weekday":  "get_weekday",
    "date_diff": "days_between",
    "search":   "web_search",
    "chat":     None,          # không cần tool
}


INTENT_PROMPT = """Bạn là bộ phân loại ý định. Đọc câu hỏi của user và trả về DUY NHẤT 1 từ trong danh sách:
weather, forecast, time, weekday, date_diff, search, chat

Định nghĩa:
- weather: hỏi thời tiết HIỆN TẠI (VD: "thời tiết Hà Nội", "trời có mưa không")
- forecast: hỏi dự báo NHIỀU NGÀY (VD: "dự báo 7 ngày", "tuần sau thế nào")
- time: hỏi giờ hiện tại (VD: "mấy giờ rồi", "bây giờ là mấy giờ")
- weekday: hỏi thứ của ngày (VD: "ngày mai thứ mấy", "17/9 là thứ mấy")
- date_diff: tính khoảng cách ngày (VD: "còn mấy ngày nữa đến Tết")
- search: tìm kiếm thông tin (VD: "giá vàng hôm nay", "tin tức")
- chat: chào hỏi, tán gẫu, không cần thông tin ngoài (VD: "xin chào", "bạn khỏe không")

Chỉ trả về 1 từ, KHÔNG giải thích.

Câu hỏi: {user_text}
Trả lời:"""


class IntentClassifier:
    """Phân loại intent bằng LLM nhỏ (qwen2.5:1.5b hoặc qwen3.5:4b)."""

    def __init__(self, log=None):
        self.log = log or logger
        self.url = config.intent_url
        self.model = config.intent_model
        self.timeout = config.intent_timeout

    async def classify(self, user_text: str) -> str:
        """Trả về 1 trong: weather, forecast, time, weekday, date_diff, search, chat."""
        prompt = INTENT_PROMPT.format(user_text=user_text)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    self.url,
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "think": False,
                        "options": {"temperature": 0.0, "num_predict": 5},
                    },
                )
                r.raise_for_status()
                data = r.json()
                raw = data.get("message", {}).get("content", "").strip().lower()

                # Clean: chỉ lấy từ đầu tiên khớp
                for intent in INTENT_TOOL_MAP.keys():
                    if intent in raw:
                        self.log.info(f"🧠 Intent: {intent}")
                        return intent

                self.log.warning(f"⚠️ Intent không rõ: '{raw}' → chat")
                return "chat"

        except Exception as e:
            self.log.warning(f"⚠️ Intent LLM lỗi: {e} → fallback chat")
            return "chat"


# Singleton
_classifier: Optional[IntentClassifier] = None


def get_intent_classifier(log=None) -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier(log=log)
    return _classifier
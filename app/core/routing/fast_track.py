"""Fast track v4 — chỉ giữ tiện ích thuần server/realtime, gỡ toàn bộ điều khiển thiết bị cứng."""
from __future__ import annotations

from datetime import date as _date, datetime as _dt, timedelta
import re
from typing import Any, Callable, Optional

from app.core.providers.tools import builtin as tools
from app.core.providers.tools.unified.register import Action

FAREWELL_RE = re.compile(
    r"^\s*(?:(?:tạm\s+biệt|chào\s+nhé|hẹn\s+gặp\s+lại|ngủ\s+ngon|"
    r"goodbye|bye)(?:\s+(?:bạn|nhé|nha|em))*[.!\s]*)$",
    re.IGNORECASE,
)

GREET_RE = re.compile(
    r"^\s*(xin\s+chào|chào|hello|hi|hey|hế\s+lô|alo)\b",
    re.IGNORECASE,
)


def is_farewell(text: str) -> bool:
    return bool(FAREWELL_RE.fullmatch(text or ""))


WEEKDAYS_VI = [
    "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
    "Thứ Sáu", "Thứ Bảy", "Chủ Nhật",
]

MATH_PREFIX_RE = re.compile(
    r"^(?:tính|giải|tính\s+toán|tính\s+giúp|tính\s+hộ|"
    r"giải\s+giúp|giải\s+hộ|bằng|kết\s+quả\s+của|"
    r"cho\s+(?:tôi|mình)\s+biết|hãy\s+tính)\s+",
    re.IGNORECASE,
)
MATH_EXPR_RE = re.compile(r"^[\d\.\+\-\*/%\^\(\)\s]+$")
MATH_WORD_EXPR_RE = re.compile(
    r"^(?:(?:không|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d+(?:[.,]\d+)?)"
    r"|cộng|trừ|nhân|chia|mũ|phẩy|x|×|÷|[()+\-*/%^.,\s])+$",
    re.IGNORECASE,
)
WORD_TO_NUM = {
    "không": "0", "một": "1", "hai": "2", "ba": "3",
    "bốn": "4", "năm": "5", "sáu": "6", "bảy": "7",
    "tám": "8", "chín": "9", "mười": "10",
}
MATH_KEYWORD_RE = re.compile(r"\b(cộng|trừ|nhân|chia|mũ|phẩy)\b", re.IGNORECASE)

TIME_RE = re.compile(
    r"^(?:bây\s+giờ\s+(?:là\s+)?mấy\s+giờ|mấy\s+giờ(?:\s+rồi)?|giờ\s+rồi)\??$",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(
    r"^(hôm\s+nay|ngày\s+mai|ngày\s+kia|hôm\s+qua)\s+(?:là\s+)?thứ\s+mấy\??$",
    re.IGNORECASE,
)
DAY_RE = re.compile(
    r"^(hôm\s+nay|ngày\s+mai)\s+(?:là\s+)?ngày\s+(?:mấy|bao\s+nhiêu)\??$",
    re.IGNORECASE,
)

NEGATED_MUSIC_RE = re.compile(
    r"\b(?:đừng|chớ|không(?:\s+(?:cần|muốn|định))?)\s+(?:phát|mở|bật|nghe)\b",
    re.IGNORECASE,
)
MUSIC_REQUEST_RE = re.compile(
    r"^\s*(?:hãy\s+)?(?:phát|mở|bật|nghe)\s+"
    r"(?:(?:bài hát|bài|nhạc)\s+)?(.+?)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_GENERIC_QUERY_RE = re.compile(
    r"^(?:nhạc(?:\s+(?:nhẹ|nhẹ\s+nhàng|buồn|vui|chill|lofi|việt|trẻ|"
    r"thiền|piano|tết|sôi\s+động|êm\s+dịu|thư\s+giãn|"
    r"học\s+bài|ngủ|ngủ\s+ngon|hot|mới|hay|remix))?"
    r"|bài(?:\s+hát)?|music|youtube|nhẹ|nhẹ\s+nhàng|buồn|vui|"
    r"vui\s+vẻ|chill|lofi|sôi\s+động|êm\s+dịu|thư\s+giãn|"
    r"học\s+bài|ngủ|ngủ\s+ngon|hot|mới|hay|một\s+bài|"
    r"bài\s+gì\s+đó|gì\s+cũng\s+được|sao\s+cũng\s+được)$",
    re.IGNORECASE,
)

CALENDAR_QUERY_RE = re.compile(
    r"\b(?:lịch(?:\s+trình|\s+hẹn|\s+làm\s+việc|\s+học)?|có\s+việc\s+gì|bận\s+gì)\b",
    re.IGNORECASE,
)


def _is_generic_music_query(query: Optional[str]) -> bool:
    if not query:
        return True
    return bool(_GENERIC_QUERY_RE.match(query.strip()))


def _norm(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[.!?,;:…]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _normalize_math(text: str) -> str:
    t = text.lower()
    for word, num in sorted(WORD_TO_NUM.items(), key=lambda x: -len(x[0])):
        t = re.sub(rf"\b{re.escape(word)}\b", num, t)
    t = re.sub(r"\bphẩy\b", ".", t)
    t = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", t)
    t = re.sub(r"(\d+),(\d+)", r"\1.\2", t)
    t = re.sub(r"\bcộng\b", "+", t)
    t = re.sub(r"\btrừ\b", "-", t)
    t = re.sub(r"\bnhân\b", "*", t)
    t = re.sub(r"\bchia\b", "/", t)
    t = re.sub(r"\bmũ\b", "**", t)
    t = re.sub(r"\b(?:bằng\s+bao\s+nhiêu|bằng)\b", "", t)
    t = re.sub(r"[x×]", "*", t)
    t = re.sub(r"÷", "/", t)
    t = re.sub(r"[^\d\+\-\*/\.\(\)\s]", "", t)
    return t.strip()


def _try_math(q_norm: str) -> Optional[str]:
    stripped = MATH_PREFIX_RE.sub("", q_norm).strip()
    if MATH_EXPR_RE.match(stripped):
        return re.sub(r"\s+", "", stripped)
    if MATH_KEYWORD_RE.search(q_norm):
        normalized = _normalize_math(q_norm)
        if normalized and MATH_EXPR_RE.match(normalized):
            return re.sub(r"\s+", "", normalized)
    return None


async def process_fast_track(
    user_text: str,
    quick_response_func: Callable,
    log: Any,
    execute_tool: Optional[Callable] = None,
) -> Any:
    try:
        from app.config import config
        if not config._get("pipeline", "fast_track_enabled", default=True):
            return None
    except Exception:
        pass

    _q = user_text.lower()
    _q_clean = "".join(c for c in _q if c.isalnum() or c.isspace()).strip()
    _q_norm = _norm(user_text)

    # 1. GREETING (0ms, time-aware)
    if GREET_RE.search(_q_clean) and len(_q_clean.split()) <= 6:
        try:
            from app.core.routing.greeting import build_greeting
            reply = build_greeting(user_text, time_aware=True)
        except Exception as e:
            log.warning(f"Greeting fallback: {e}")
            reply = "Chào bạn!"
        await quick_response_func(user_text, reply)
        return reply

    # 2. MUSIC REQUEST (chỉ khi có tên bài/từ khóa cụ thể trên server)
    music_match = MUSIC_REQUEST_RE.match(user_text)
    if music_match and execute_tool and not NEGATED_MUSIC_RE.search(_q_clean):
        query = music_match.group(1).strip(" .,!?:;")
        query_lower = query.lower()
        if (
            not _is_generic_music_query(query)
            and query
            and query_lower not in {"đi", "lên", "nào", "nhé", "nha"}
        ):
            try:
                result = await execute_tool("play_music", {"query": query})
                msg = str(getattr(result, "response", None) or getattr(result, "result", None) or "").strip()
                action = getattr(result, "action", None)
                if action not in (Action.RESPONSE, Action.RECORD) and not msg:
                    msg = "Mình không phát được bài này lúc này."
                await quick_response_func(user_text, msg)
                return msg
            except Exception as e:
                log.warning(f"Music fast-track lỗi: {e}")
                msg = "Mình không phát được bài này lúc này."
                await quick_response_func(user_text, msg)
                return msg

    # 3. MATH
    math_input = MATH_PREFIX_RE.sub("", _q_norm).strip()
    math_candidate = (
        bool(MATH_EXPR_RE.fullmatch(math_input))
        or bool(MATH_WORD_EXPR_RE.fullmatch(math_input))
    )
    expr = _try_math(_q_norm) if math_candidate else None
    if expr:
        try:
            result = await tools._tool_calculate(expr)
            await quick_response_func(user_text, result)
            return result
        except Exception as e:
            log.warning(f"Math fast-track lỗi: {e}")

    # 4. TIME / WEEKDAY / DAY
    if TIME_RE.fullmatch(_q_norm):
        now = _dt.now()
        reply = f"Bây giờ là {now.hour} giờ {now.minute} phút."
        await quick_response_func(user_text, reply)
        return reply

    m_wk = WEEKDAY_RE.fullmatch(_q_norm)
    if m_wk:
        offset = 1 if "ngày mai" in m_wk.group(1) else (-1 if "hôm qua" in m_wk.group(1) else 0)
        day = _dt.now() + timedelta(days=offset)
        reply = f"{WEEKDAYS_VI[day.weekday()]}."
        await quick_response_func(user_text, reply)
        return reply

    m_day = DAY_RE.fullmatch(_q_norm)
    if m_day:
        offset = 1 if "ngày mai" in m_day.group(1) else 0
        day = _dt.now() + timedelta(days=offset)
        prefix = "Ngày mai" if offset == 1 else "Hôm nay"
        reply = f"{prefix} là ngày {day.day} tháng {day.month} năm {day.year}."
        await quick_response_func(user_text, reply)
        return reply

    # 5. CALENDAR QUERY (bơm ngữ cảnh ngày thực tế cho LLM diễn đạt)
    if CALENDAR_QUERY_RE.search(_q_clean) and execute_tool:
        if not re.search(r"\b(?:thêm|tạo|đặt|sửa|đổi|xóa|hủy)\b", _q_clean):
            try:
                today = _date.today()
                if "ngày mai" in _q_clean or "mai" in _q_clean.split():
                    start_d = end_d = today + timedelta(days=1)
                elif "tuần này" in _q_clean:
                    start_d = today
                    end_d = today + timedelta(days=6)
                else:
                    start_d = end_d = today

                result = await execute_tool(
                    "list_calendar",
                    {"start_date": start_d.isoformat(), "end_date": end_d.isoformat()},
                )
                if getattr(result, "action", None) == Action.REQLLM and getattr(result, "result", None):
                    return {"__llm_context__": str(result.result).strip()}
            except Exception as e:
                log.warning(f"Calendar fast-track lỗi: {e}")

    return None
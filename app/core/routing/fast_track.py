"""Fast track — deterministic routing trước LLM."""
import re
from datetime import datetime, timedelta

from app.core.providers.tools import impl as tools
from app.core.providers.tools.gold_price import _tool_get_gold_price


NEGATION_PATTERNS = re.compile(
    r"\b(đừng|chớ|không\s+cần|không\s+được|khỏi)\b", re.IGNORECASE
)

GREETING_SET = {
    "chào", "chào bạn", "chào đèn", "chào em", "chào anh", "chào chị",
    "hi", "hello", "hey", "alo", "xin chào", "hế lô", "hê lô",
    "chào buổi sáng", "chào buổi chiều", "chào buổi tối", "chào buổi trưa",
    "good morning", "good afternoon", "good evening",
}

SMALL_TALK = {
    "cảm ơn": "Không có gì.",
    "cảm ơn bạn": "Không có gì.",
    "cảm ơn nhé": "Không có gì.",
    "cảm ơn nhiều": "Không có gì.",
    "bạn khỏe không": "Mình vẫn hoạt động tốt.",
    "khỏe không": "Mình vẫn hoạt động tốt.",
    "tạm biệt": "Tạm biệt bạn.",
    "bye": "Tạm biệt bạn.",
    "ngủ ngon": "Chúc bạn ngủ ngon.",
}

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

# ═══ MATH ═══
MATH_PREFIX_RE = re.compile(
    r"^(?:tính|giải|tính\s+toán|tính\s+giúp|tính\s+hộ|"
    r"giải\s+giúp|giải\s+hộ|bằng|kết\s+quả\s+của|"
    r"cho\s+(?:tôi|mình)\s+biết|hãy\s+tính)\s+",
    re.IGNORECASE,
)
MATH_EXPR_RE = re.compile(
    r"^\s*(?:\d+(?:[.,]\d+)?\s*(?:[+\-*/x×÷^]\s*\d+(?:[.,]\d+)?\s*)+)\s*$",
    re.IGNORECASE,
)
WORD_TO_NUM = {
    "không": "0", "một": "1", "hai": "2", "ba": "3", "bốn": "4",
    "năm": "5", "sáu": "6", "bảy": "7", "tám": "8", "chín": "9",
    "mười": "10",
}
MATH_KEYWORD_RE = re.compile(r"\b(cộng|trừ|nhân|chia|mũ|phẩy)\b", re.IGNORECASE)

# ═══ WEATHER ═══
CITY_TRAILING_RE = re.compile(
    r"\s+(?:hôm\s+nay|ngày\s+mai|ngày\s+kia|bây\s+giờ|"
    r"thế\s+nào|ra\s+sao|như\s+thế\s+nào|có\s+mưa\s+không|"
    r"thế\s+ế|có\s+gì\s+mới|bao\s+nhiêu\s+độ)\s*$",
    re.IGNORECASE,
)
CITY_PREFIX_RE = re.compile(
    r"^(?:ở|tại|thành\s+phố|tp\.?|tỉnh)\s+", re.IGNORECASE
)
CITY_ALIASES = {
    "hn": "Hà Nội", "hà nội": "Hà Nội",
    "hcm": "Hồ Chí Minh", "sài gòn": "Hồ Chí Minh", "tphcm": "Hồ Chí Minh",
    "đn": "Đà Nẵng", "đà nẵng": "Đà Nẵng",
    "hp": "Hải Phòng", "hải phòng": "Hải Phòng",
    "ct": "Cần Thơ", "cần thơ": "Cần Thơ",
}

# ═══ TIME ═══
TIME_RE = re.compile(r"\b(mấy\s+giờ|giờ\s+rồi|bây\s+giờ\s+là\s+mấy|bây\s+giờ)\b", re.IGNORECASE)
WEEKDAY_RE = re.compile(r"\b(hôm\s+nay|ngày\s+mai|ngày\s+kia|hôm\s+qua)\s+(?:là\s+)?thứ\s+mấy\b", re.IGNORECASE)
DAY_RE = re.compile(r"\b(hôm\s+nay|ngày\s+mai)\s+(?:là\s+)?ngày\s+(?:mấy|bao\s+nhiêu)\b", re.IGNORECASE)
LUNAR_RE = re.compile(r"\b(âm\s+lịch|ngày\s+âm|mùng\s+mấy|rằm)\b", re.IGNORECASE)
DAYS_BETWEEN_RE = re.compile(r"\bcòn\s+bao\s+nhiêu\s+ngày\s+(?:nữa\s+)?(?:đến|tới)\s+(.+)$", re.IGNORECASE)

# ═══ DEVICE ═══
COLOR_TEMP_RE = re.compile(
    r"\b(?:đổi|chỉnh|đặt)\s+(?:màu|nhiệt\s+độ\s+màu)\s+(?:đèn\s+)?(?:sang\s+)?(\d{1,3})",
    re.IGNORECASE,
)
BRIGHTNESS_RE = re.compile(
    r"(?:độ\s+sáng|sáng)\s*(?:là|còn|đến|lên)?\s*(\d{1,3})\s*(?:%|phần\s+trăm)?",
    re.IGNORECASE,
)

# ═══ OTHERS ═══
GOLD_RE = re.compile(r"\b(giá\s+vàng|vàng\s+sjc|vàng\s+miếng)\b", re.IGNORECASE)
WEATHER_RE = re.compile(
    r"^(?:thời\s+tiết|dự\s+báo\s+thời\s+tiết|thời\s+tiết\s+hôm\s+nay)"
    r"(?:\s+(?:ở|tại))?\s*(?P<city>.*)$",
    re.IGNORECASE,
)
FORECAST_RE = re.compile(r"\bdự\s+báo\s+thời\s+tiết\b", re.IGNORECASE)
SENSOR_RE = re.compile(r"\b(nhiệt\s+độ\s+phòng|độ\s+ẩm|ánh\s+sáng|cảm\s+biến)\b", re.IGNORECASE)


def _norm(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[.!?,;:…]+$", "", t)
    return re.sub(r"\s+", " ", t)


def _normalize_math(text: str) -> str:
    """Chuẩn hóa 'hai phẩy năm cộng ba' → '2.5+3'."""
    t = text.lower()
    for word, num in sorted(WORD_TO_NUM.items(), key=lambda x: -len(x[0])):
        t = re.sub(rf"\b{re.escape(word)}\b", num, t)
    t = re.sub(r"\bphẩy\b", ".", t)
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


def _try_math(q_norm: str) -> str | None:
    stripped = MATH_PREFIX_RE.sub("", q_norm).strip()
    if MATH_EXPR_RE.match(stripped):
        return re.sub(r"\s+", "", stripped)
    if MATH_KEYWORD_RE.search(q_norm):
        normalized = _normalize_math(q_norm)
        if normalized and MATH_EXPR_RE.match(normalized):
            return re.sub(r"\s+", "", normalized)
    return None


def _strip_city(raw: str) -> str:
    c = (raw or "").strip()
    c = CITY_TRAILING_RE.sub("", c).strip()
    c = CITY_PREFIX_RE.sub("", c).strip()
    c = re.sub(r"[.!?,;:…]+$", "", c).strip()
    if not c:
        return ""
    return CITY_ALIASES.get(c.lower(), c)


async def process_fast_track(user_text: str, quick_response_func, log) -> str | None:
    """Signature tương thích connection.py."""
    q = user_text.lower()
    q_norm = _norm(user_text)

    if NEGATION_PATTERNS.search(q):
        return None

    # Greeting
    if q_norm in GREETING_SET:
        reply = "Chào bạn!"
        await quick_response_func(user_text, reply)
        return reply

    # Small talk
    if q_norm in SMALL_TALK:
        reply = SMALL_TALK[q_norm]
        await quick_response_func(user_text, reply)
        return reply

    # Math (đặt sớm để không bị LLM chọn web_search)
    expr = _try_math(q_norm)
    if expr:
        try:
            result = await tools._tool_calculate(expr)
            await quick_response_func(user_text, result)
            return result
        except Exception as e:
            log.warning(f"Math fast-track lỗi: {e}")

    # Đèn
    if re.search(r"\b(bật|mở)\s+(?:cái\s+)?đèn\b", q) or q_norm in {"bật đèn", "mở đèn"}:
        result = await tools._send_mcp_command("Lamp.TurnOn")
        msg = "Đã bật đèn." if result.get("ok") else f"Không bật được đèn: {result.get('error')}"
        await quick_response_func(user_text, msg)
        return msg

    if re.search(r"\b(tắt|đóng)\s+(?:cái\s+)?đèn\b", q) or q_norm in {"tắt đèn", "đóng đèn"}:
        result = await tools._send_mcp_command("Lamp.TurnOff")
        msg = "Đã tắt đèn." if result.get("ok") else f"Không tắt được đèn: {result.get('error')}"
        await quick_response_func(user_text, msg)
        return msg

    m = BRIGHTNESS_RE.search(q)
    if m and "đèn" in q:
        brightness = max(0, min(100, int(m.group(1))))
        result = await tools._send_mcp_command("Lamp.SetBrightness", {"value": brightness})
        msg = f"Đã đặt độ sáng {brightness}%." if result.get("ok") else f"Không đổi được độ sáng: {result.get('error')}"
        await quick_response_func(user_text, msg)
        return msg

    m = COLOR_TEMP_RE.search(q)
    if m and "đèn" in q:
        ct = max(0, min(100, int(m.group(1))))
        result = await tools._send_mcp_command("Lamp.SetColorTemp", {"value": ct})
        msg = f"Đã đặt nhiệt độ màu {ct}." if result.get("ok") else f"Không đổi được màu: {result.get('error')}"
        await quick_response_func(user_text, msg)
        return msg

    # Time
    now = datetime.now()
    if TIME_RE.search(q_norm):
        reply = f"Bây giờ là {now.hour} giờ {now.minute} phút."
        await quick_response_func(user_text, reply)
        return reply

    m = WEEKDAY_RE.search(q_norm)
    if m:
        which = m.group(1).lower()
        offset = 0
        if "mai" in which: offset = 1
        elif "kia" in which: offset = 2
        elif "qua" in which: offset = -1
        target = now + timedelta(days=offset)
        reply = f"{target.strftime('%d/%m/%Y')} là {WEEKDAYS_VI[target.weekday()]}."
        await quick_response_func(user_text, reply)
        return reply

    if DAY_RE.search(q_norm):
        reply = f"Hôm nay là ngày {now.day} tháng {now.month} năm {now.year}."
        await quick_response_func(user_text, reply)
        return reply

    if LUNAR_RE.search(q_norm):
        try:
            reply = await tools._tool_get_lunar("hôm nay")
            await quick_response_func(user_text, reply)
            return reply
        except Exception as e:
            log.warning(f"Lunar lỗi: {e}")

    m = DAYS_BETWEEN_RE.search(q_norm)
    if m:
        try:
            reply = await tools._tool_days_between("hôm nay", m.group(1).strip())
            await quick_response_func(user_text, reply)
            return reply
        except Exception as e:
            log.warning(f"days_between lỗi: {e}")

    # Sensor
    if SENSOR_RE.search(q_norm):
        reply = await tools._tool_get_sensor("all")
        await quick_response_func(user_text, reply)
        return reply

    # Gold
    if GOLD_RE.search(q_norm):
        reply = await _tool_get_gold_price()
        await quick_response_func(user_text, reply)
        return reply

    # Weather
    wm = WEATHER_RE.match(q_norm)
    if wm or FORECAST_RE.search(q_norm):
        raw_city = wm.group("city") if wm else ""
        city = _strip_city(raw_city) or "Hà Nội"
        is_forecast = bool(FORECAST_RE.search(q_norm))
        if is_forecast:
            reply = await tools._tool_get_forecast(city, 3)
        else:
            reply = await tools._tool_get_weather(city)
        await quick_response_func(user_text, reply)
        return reply

    return None
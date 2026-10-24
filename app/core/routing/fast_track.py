"""Fast track — deterministic routing trước LLM."""
import re
from datetime import datetime, timedelta
import random

NATURAL_REPLIES = {
    "chào": ["Chào bạn!", "Ơ chào bạn!", "Chào nhé!"],
    "cảm ơn": ["Không có gì đâu.", "Có gì đâu mà.", "Vui thôi!"],
    "tạm biệt": ["Tạm biệt bạn.", "Đi nhé!", "Hẹn gặp lại."],
    "ngủ ngon": ["Ngủ ngon nhé.", "Chúc bạn ngon giấc."],
    "bạn khỏe không": ["Mình vẫn ổn.", "Mình chạy tốt lắm."],
}


def _pick_natural(key: str) -> str:
    replies = NATURAL_REPLIES.get(key, [])
    return random.choice(replies) if replies else ""


from app.core.providers.tools import impl as tools
# from app.core.providers.tools.gold_price import _tool_get_gold_price  # disabled


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
_CITY_TRAILING_RE_LEGACY = CITY_TRAILING_RE
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
    r"^(?:(?:hôm\s+nay|ngày\s+mai|ngày\s+kia)\s+)?"
    r"(?:thời\s+tiết|dự\s+báo\s+thời\s+tiết)"
    r"(?:\s+(?:ở|tại))?\s*(?P<city>.*)$",
    re.IGNORECASE,
)

# Fallback cho input không dấu
WEATHER_RE_ASCII = re.compile(
    r"^(?:(?:hom\s+nay|ngay\s+mai|ngay\s+kia)\s+)?"
    r"(?:thoi\s+tiet|du\s+bao\s+thoi\s+tiet)"
    r"(?:\s+(?:o|tai))?\s*(?P<city>.*)$",
    re.IGNORECASE,
)
FORECAST_RE = re.compile(r"\bdự\s+báo\s+thời\s+tiết\b", re.IGNORECASE)
SENSOR_RE = re.compile(r"\b(nhiệt\s+độ\s+phòng|độ\s+ẩm|ánh\s+sáng|cảm\s+biến)\b", re.IGNORECASE)



import unicodedata

def _ascii_lower(text: str) -> str:
    """'Xin Chào!' → 'xin chao' (bỏ dấu tiếng Việt để match)."""
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[.!?,;:…]+$", "", t)
    t = ''.join(
        c for c in unicodedata.normalize('NFD', t)
        if unicodedata.category(c) != 'Mn'
    )
    t = t.replace('đ', 'd')
    return re.sub(r"\s+", " ", t).strip()


_GREETING_SET_ASCII = {_ascii_lower(g) for g in GREETING_SET}
_SMALL_TALK_ASCII = {_ascii_lower(k): v for k, v in SMALL_TALK.items()}


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


# ═══ CITY STRIPPING ═══
# Noise words có thể xuất hiện ở bất kỳ vị trí nào trong raw city
_CITY_MID_NOISE_RE = re.compile(
    r"(?<!\w)(?:"
    r"hôm\s+nay|hom\s+nay|"
    r"hôm\s+qua|hom\s+qua|"
    r"hôm\s+kia|hom\s+kia|"
    r"ngày\s+mai|ngay\s+mai|"
    r"ngày\s+kia|ngay\s+kia|"
    r"bữa\s+nay|bua\s+nay|"
    r"lúc\s+này|luc\s+nay|"
    r"giờ\s+này|gio\s+nay|"
    r"bây\s+giờ|bay\s+gio|"
    r"tuần\s+này|tuan\s+nay|"
    r"tuần\s+sau|tuan\s+sau|"
    r"tuần\s+trước|tuan\s+truoc|"
    r"thế\s+nào|the\s+nao|"
    r"như\s+thế\s+nào|nhu\s+the\s+nao|"
    r"có\s+mưa\s+không|co\s+mua\s+khong|"
    r"có\s+gì\s+mới|co\s+gi\s+moi|"
    r"bao\s+nhiêu\s+độ|bao\s+nhieu\s+do|"
    r"thành\s+phố|thanh\s+pho|"
    r"ra\s+sao|"
    r"ở|tại|đâu|dau"
    r")(?!\w)",
    re.IGNORECASE,
)

# Trailing noise đơn âm tiết (lặp strip)
_CITY_TAIL_NOISE_RE = re.compile(
    r"\s+(?:mai|mốt|mot)\s*$",
    re.IGNORECASE,
)

# Chỉ còn noise → coi như rỗng
_CITY_PURE_NOISE_ASCII = {
    "dau", "o", "tai",
    "the nao", "ra sao", "nhu the nao",
    "hom nay", "hom qua", "hom kia",
    "ngay mai", "ngay kia",
    "bao nhieu do", "co mua khong", "co gi moi",
    "thanh pho",
}


def _strip_city(raw: str) -> str:
    """Chuẩn hóa city từ raw text.

    - Xóa prefix (ở/tại/thành phố/tp/tỉnh)
    - Xóa noise word ở bất kỳ vị trí (hôm nay, thế nào, ở, ...)
    - Xóa trailing noise (mai, mốt, ...) — lặp đến khi ổn định
    - Trả "" nếu chỉ còn noise → caller tự fallback "Hà Nội"
    """
    c = (raw or "").strip()
    if not c:
        return ""

    # 1. Prefix (ở/tại/...)
    c = CITY_PREFIX_RE.sub("", c).strip()

    # 2. Multi-word noise ở giữa/cuối
    c = _CITY_MID_NOISE_RE.sub(" ", c).strip()

    # 3. Trailing single-word noise (loop để xử lý nhiều lớp)
    for _ in range(5):
        new_c = _CITY_TRAILING_RE_LEGACY.sub("", c).strip()
        new_c = _CITY_TAIL_NOISE_RE.sub("", new_c).strip()
        if new_c == c:
            break
        c = new_c

    # 4. Cleanup
    c = re.sub(r"[.!?,;:…]+$", "", c).strip()
    c = re.sub(r"\s+", " ", c).strip()
    if not c:
        return ""

    # 5. Chỉ còn noise → ""
    if _ascii_lower(c) in _CITY_PURE_NOISE_ASCII:
        return ""

    return CITY_ALIASES.get(c.lower(), c)


async def process_fast_track(user_text: str, quick_response_func, log) -> str | None:
    """Signature tương thích connection.py."""
    q = user_text.lower()
    q_norm = _norm(user_text)

    if NEGATION_PATTERNS.search(q):
        return None

    q_ascii = _ascii_lower(user_text)

    # Greeting (cả có dấu lẫn không dấu)
    if q_norm in GREETING_SET or q_ascii in _GREETING_SET_ASCII:
        reply = "Chào bạn!"
        await quick_response_func(user_text, reply)
        return reply

    # Small talk (cả có dấu lẫn không dấu)
    reply = SMALL_TALK.get(q_norm) or _SMALL_TALK_ASCII.get(q_ascii)
    if reply:
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

    # Gold — dùng web_search vì tool gold_price đã bị disable
    if GOLD_RE.search(q_norm):
        try:
            raw = await tools._tool_web_search(user_text)
            reply = tools._compact_text(raw, max_chars=300)
            await quick_response_func(user_text, reply)
            return reply
        except Exception as e:
            log.warning(f"Gold fast-track lỗi: {e}")

    # Weather (fallback sang dạng không dấu)
    wm = WEATHER_RE.match(q_norm) or WEATHER_RE_ASCII.match(q_ascii)
    if wm or FORECAST_RE.search(q_norm):
        raw_city = wm.group("city") if wm else ""
        city = _strip_city(raw_city) or "Hà Nội"
        is_forecast = bool(FORECAST_RE.search(q_norm))
        if log:
            log.info(
                f"🌤️ Weather: raw={raw_city!r} → city={city!r} "
                f"forecast={is_forecast}"
            )
        if is_forecast:
            reply = await tools._tool_get_forecast(city, 3)
        else:
            reply = await tools._tool_get_weather(city)
        await quick_response_func(user_text, reply)
        return reply

    return None
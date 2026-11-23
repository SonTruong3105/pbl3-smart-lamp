"""Fast track v3 — routing deterministic trước LLM (tự nhiên + realtime)."""
import re
from datetime import datetime as _dt, timedelta
from app.core.providers.tools import builtin as tools
from app.core.providers.tools.unified.register import Action


FAREWELL_RE = re.compile(
    r"^\s*(?:(?:tạm\s+biệt|chào\s+nhé|hẹn\s+gặp\s+lại|ngủ\s+ngon|"
    r"goodbye|bye)(?:\s+(?:bạn|đèn|nhé|nha|em))*[.!\s]*)$",
    re.IGNORECASE,
)


def is_farewell(text: str) -> bool:
    return bool(FAREWELL_RE.fullmatch(text or ""))

NEGATED_DEVICE_RE = re.compile(
    r"\b(?:đừng|chớ|khỏi|không(?:\s+(?:cần|được|muốn|định))?)\s+"
    r"(?:có\s+)?(?:bật|mở|tắt|đóng|đổi|chỉnh)\b",
    re.IGNORECASE,
)

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

MATH_PREFIX_RE = re.compile(
    r"^(?:tính|giải|tính\s+toán|tính\s+giúp|tính\s+hộ|"
    r"giải\s+giúp|giải\s+hộ|bằng|kết\s+quả\s+của|"
    r"cho\s+(?:tôi|mình)\s+biết|hãy\s+tính)\s+", re.IGNORECASE,
)
MATH_EXPR_RE = re.compile(r"^[\d\.\+\-\*/%\^\(\)\s]+$")
MATH_WORD_EXPR_RE = re.compile(
    r"^(?:(?:không|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d+(?:[.,]\d+)?)"
    r"|cộng|trừ|nhân|chia|mũ|phẩy|x|×|÷|[()+\-*/%^.,\s])+$",
    re.IGNORECASE,
)
WORD_TO_NUM = {"không": "0", "một": "1", "hai": "2", "ba": "3",
               "bốn": "4", "năm": "5", "sáu": "6", "bảy": "7",
               "tám": "8", "chín": "9", "mười": "10"}
MATH_KEYWORD_RE = re.compile(r"\b(cộng|trừ|nhân|chia|mũ|phẩy)\b", re.IGNORECASE)

TIME_RE = re.compile(
    r"^(?:bây\s+giờ\s+(?:là\s+)?mấy\s+giờ|mấy\s+giờ(?:\s+rồi)?|giờ\s+rồi)\??$",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(r"^(hôm\s+nay|ngày\s+mai|ngày\s+kia|hôm\s+qua)\s+(?:là\s+)?thứ\s+mấy\??$", re.IGNORECASE)
DAY_RE = re.compile(r"^(hôm\s+nay|ngày\s+mai)\s+(?:là\s+)?ngày\s+(?:mấy|bao\s+nhiêu)\??$", re.IGNORECASE)

COLOR_TEMP_RE = re.compile(
    r"\b(?:đổi|chỉnh|đặt|chuyển)\s+(?:màu|nhiệt\s+độ\s+màu)\s+(?:đèn\s+)?(?:sang\s+)?(\d{1,3})",
    re.IGNORECASE,
)
ALLOWED_COLOR_TEMPS = {3000, 4500, 6000}
COLOR_WARM_RE = re.compile(r"\b(?:màu\s+ấm|ánh\s+sáng\s+ấm|vàng\s+ấm)\b", re.IGNORECASE)
COLOR_COOL_RE = re.compile(r"\b(?:màu\s+lạnh|ánh\s+sáng\s+lạnh|trắng\s+lạnh)\b", re.IGNORECASE)
BRIGHTNESS_RE = re.compile(
    r"(?:độ\s+sáng|sáng)\s*(?:là|còn|đến|lên|mức)?\s*(\d{1,3})\s*(?:%|phần\s+trăm)?",
    re.IGNORECASE,
)
SCENE_RE = re.compile(
    r"\b(?:chuyển|đổi|bật|mở)\s+(?:sang\s+)?(?:chế\s+độ|kịch\s+bản|scene)\s+(.+?)(?:\.|!|\?|$)",
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


def _is_generic_music_query(query):
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


def _try_math(q_norm: str):
    stripped = MATH_PREFIX_RE.sub("", q_norm).strip()
    if MATH_EXPR_RE.match(stripped):
        return re.sub(r"\s+", "", stripped)
    if MATH_KEYWORD_RE.search(q_norm):
        normalized = _normalize_math(q_norm)
        if normalized and MATH_EXPR_RE.match(normalized):
            return re.sub(r"\s+", "", normalized)
    return None


async def process_fast_track(user_text: str, quick_response_func, log,
                             execute_tool=None):
    try:
        from app.config import config
        if not config._get("pipeline", "fast_track_enabled", default=True):
            return None
    except Exception:
        pass

    _q = user_text.lower()
    _q_clean = "".join(c for c in _q if c.isalnum() or c.isspace()).strip()
    _q_norm = _norm(user_text)

    if NEGATED_DEVICE_RE.search(_q_clean):
        # Never let a generative intent/model turn a negation into a device action.
        reply = "Được, mình sẽ không thực hiện lệnh điều khiển đèn đó."
        await quick_response_func(user_text, reply)
        return reply

    async def _run_light(action, extra=None):
        if execute_tool is None:
            return None
        args = {"action": action}
        if extra:
            args.update(extra)
        try:
            result = await execute_tool("control_light", args)
        except Exception as e:
            log.warning(f"Fast Track tool lỗi: {e}")
            return "Mình đã thử điều khiển đèn nhưng có lỗi xảy ra."
        if result.action in (Action.RESPONSE, Action.RECORD, Action.REQLLM, Action.ERROR):
            return str(result.response or result.result or "Mình không điều khiển được đèn lúc này.").strip()
        return None

    # ═══════════════════════════════════════════════════════════
    # GREETING (0ms, tự nhiên + time-aware)
    # ═══════════════════════════════════════════════════════════
    _greet_pat = re.compile(
        r"^\s*(xin\s+chào|chào|hello|hi|hey|hế\s+lô|alo|chào\s+đèn|đèn\s+ơi)\b",
        re.IGNORECASE,
    )
    if _greet_pat.search(_q_clean) and len(_q_clean.split()) <= 6:
        try:
            from app.core.routing.greeting import build_greeting
            reply = build_greeting(user_text, time_aware=True)
        except Exception as e:
            log.warning(f"Greeting fallback: {e}")
            reply = "Chào bạn!"
        await quick_response_func(user_text, reply)
        return reply

    music_match = MUSIC_REQUEST_RE.match(user_text)
    if music_match and execute_tool and not NEGATED_MUSIC_RE.search(_q_clean):
        query = music_match.group(1).strip(" .,!?:;")
        query_lower = query.lower()
        if _is_generic_music_query(query):
            pass
        elif (
            query
            and query_lower not in {"đi", "lên", "nào", "nhé", "nha"}
            and not query_lower.startswith(("đèn", "điện"))
        ):
            try:
                result = await execute_tool("play_music", {"query": query})
                msg = str(result.response or result.result or "").strip()
                if result.action not in (Action.RESPONSE, Action.RECORD) and not msg:
                    msg = "Mình không phát được bài này lúc này."
                await quick_response_func(user_text, msg)
                return msg
            except Exception as e:
                log.warning(f"Music fast-track lỗi: {e}")
                msg = "Mình không phát được bài này lúc này."
                await quick_response_func(user_text, msg)
                return msg

    if NEGATED_DEVICE_RE.search(_q_clean):
        return None

    _on_triggers = ["bật đèn", "mở đèn", "bật cái đèn", "mở cái đèn",
                    "đèn ơi bật", "bật lên", "bật điện"]
    _off_triggers = ["tắt đèn", "đóng đèn", "tắt cái đèn", "đóng cái đèn",
                     "đèn ơi tắt", "tắt đi", "tắt điện"]

    if not execute_tool:
        return None

    if any(t in _q_clean for t in _on_triggers):
        msg = await _run_light("on")
        if msg:
            await quick_response_func(user_text, msg)
            return msg

    if any(t in _q_clean for t in _off_triggers):
        msg = await _run_light("off")
        if msg:
            await quick_response_func(user_text, msg)
            return msg

    m = BRIGHTNESS_RE.search(_q_clean)
    if m and "đèn" in _q_clean:
        try:
            val = int(m.group(1))
            if 0 <= val <= 100:
                msg = await _run_light("set", {"brightness": val})
                if msg:
                    await quick_response_func(user_text, msg)
                    return msg
        except (ValueError, IndexError):
            pass

    m = COLOR_TEMP_RE.search(_q_clean)
    if m:
        try:
            kelvin = int(m.group(1))
            if kelvin in ALLOWED_COLOR_TEMPS:
                msg = await _run_light("set", {"color_temp": kelvin})
                if msg:
                    await quick_response_func(user_text, msg)
                    return msg
        except (ValueError, IndexError):
            pass

    if "đèn" in _q_clean:
        if COLOR_WARM_RE.search(_q_clean):
            msg = await _run_light("set", {"color_temp": 3000})
            if msg:
                await quick_response_func(user_text, msg)
                return msg
        if COLOR_COOL_RE.search(_q_clean):
            msg = await _run_light("set", {"color_temp": 6000})
            if msg:
                await quick_response_func(user_text, msg)
                return msg

    m = SCENE_RE.search(_q_clean)
    if m:
        scene_name = m.group(1).strip()
        try:
            result = await execute_tool("set_scene", {"scene": scene_name})
            if result.action in (Action.RESPONSE, Action.RECORD):
                msg = str(result.response or result.result or "").strip()
                if msg:
                    await quick_response_func(user_text, msg)
                    return msg
        except Exception as e:
            log.warning(f"Fast Track scene lỗi: {e}")

    q_norm = _norm(user_text)
    # Only fast-track standalone arithmetic or explicitly introduced calculations;
    # otherwise words like "trừ" in natural requests can be misread as operators.
    math_input = MATH_PREFIX_RE.sub("", q_norm).strip()
    math_candidate = (
        bool(MATH_EXPR_RE.fullmatch(math_input))
        or bool(MATH_WORD_EXPR_RE.fullmatch(math_input))
    )
    if math_candidate:
        expr = _try_math(q_norm)
    else:
        expr = None
    if expr:
        try:
            result = await tools._tool_calculate(expr)
            await quick_response_func(user_text, result)
            return result
        except Exception as e:
            log.warning(f"Math fast-track lỗi: {e}")

    if TIME_RE.fullmatch(_q_norm):
        now = _dt.now()
        reply = f"Bây giờ là {now.hour} giờ {now.minute} phút."
        await quick_response_func(user_text, reply)
        return reply

    if WEEKDAY_RE.fullmatch(_q_norm):
        match = WEEKDAY_RE.fullmatch(_q_norm)
        offset = 1 if "ngày mai" in match.group(1) else (-1 if "hôm qua" in match.group(1) else 0)
        day = _dt.now() + timedelta(days=offset)
        reply = f"{WEEKDAYS_VI[day.weekday()]}."
        await quick_response_func(user_text, reply)
        return reply

    if DAY_RE.fullmatch(_q_norm):
        match = DAY_RE.fullmatch(_q_norm)
        offset = 1 if "ngày mai" in match.group(1) else 0
        day = _dt.now() + timedelta(days=offset)
        prefix = "Ngày mai" if offset == 1 else "Hôm nay"
        reply = f"{prefix} là ngày {day.day} tháng {day.month} năm {day.year}."
        await quick_response_func(user_text, reply)
        return reply
    # Fast-track lấy dữ liệu lịch chính xác 100% ngày thực tế, sau đó nhờ LLM viết lại cho tự nhiên
    CALENDAR_QUERY_RE = re.compile(
        r"\b(?:lịch(?:\s+trình|\s+hẹn|\s+làm\s+việc|\s+học)?|có\s+việc\s+gì|bận\s+gì)\b",
        re.IGNORECASE,
    )
    if CALENDAR_QUERY_RE.search(_q_clean) and execute_tool:
        # Không bắt các lệnh thêm/sửa/xóa lịch
        if not re.search(r"\b(?:thêm|tạo|đặt|sửa|đổi|xóa|hủy)\b", _q_clean):
            try:
                from datetime import date as _date, timedelta as _td
                today = _date.today()
                if "ngày mai" in _q_clean or "mai" in _q_clean.split():
                    start_d = end_d = today + _td(days=1)
                elif "tuần này" in _q_clean:
                    start_d = today
                    end_d = today + _td(days=6)
                else:
                    start_d = end_d = today

                result = await execute_tool(
                    "list_calendar",
                    {"start_date": start_d.isoformat(), "end_date": end_d.isoformat()},
                )
                if result.action == Action.REQLLM and result.result:
                    # Trả về dict đặc biệt để connection.py biết cần đưa cho LLM diễn đạt lại
                    return {"__llm_context__": str(result.result).strip()}
            except Exception as e:
                log.warning(f"Calendar fast-track lỗi: {e}")
    return None
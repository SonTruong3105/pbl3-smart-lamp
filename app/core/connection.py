"""ConnectionHandler — xử lý vòng đời 1 WebSocket, TTS song song."""
import asyncio
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
import io
import json
import re
import time
from typing import Awaitable, Callable, Optional
import wave

from fastapi import WebSocket

from app.config import config
from app.core.automation import set_ai_visual_state
from app.core.logger import get_session_logger
from app.core.providers.asr import phowhisper  # noqa
from app.core.providers.base import ProviderRegistry
from app.core.providers.intent import (
    FunctionCallIntentProvider,
    IntentLLMProvider,
    NoIntentProvider,
)
from app.core.providers.llm import ollama  # noqa
from app.core.providers.memory import local, none  # noqa
import app.core.providers.tools.plugins  # noqa: F401 — đăng ký tool
from app.core.providers.tools.registry import TOOLS_SCHEMA
from app.core.providers.tools.unified import (
    Action,
    ActionResponse,
    UnifiedToolHandler,
)
from app.core.providers.tts import edge, piper, vieneu  # noqa
from app.core.routing.fast_track import (
    FAREWELL_RE as _FAREWELL_RE,
    WEEKDAYS_VI as _WEEKDAYS_VI,
    _norm,
    process_fast_track,
)
from app.core.routing.intent_filter import (
    build_tool_schema,
    is_music_request,
    looks_like_pure_chat,
)
from app.core.utils.audio import any_to_wav
from app.core.utils.audio_sync import AudioReorderer
from app.core.utils.dialogue import Dialogue, Message
from app.core.utils.text_utils import (
    clean_response as _clean_response,
    compact_tool_result as _compact_tool_result,
    extract_sentences,
    filter_chinese as _filter_chinese,
)
from app.core.utils.tts_cache import get_cache
from app.music import MusicError, ogg_to_browser_mp3

_VN_TZ = _tz(_td(hours=7))

_VI_KELVIN_WORDS = {
    "một nghìn": 1000, "một ngàn": 1000,
    "một nghìn rưỡi": 1500, "một ngàn rưỡi": 1500,
    "một nghìn năm trăm": 1500, "một ngàn năm trăm": 1500,
    "hai nghìn": 2000, "hai ngàn": 2000,
    "hai nghìn rưỡi": 2500, "hai ngàn rưỡi": 2500,
    "hai nghìn bảy": 2700, "hai nghìn bảy trăm": 2700,
    "ba nghìn": 3000, "ba ngàn": 3000,
    "ba nghìn rưỡi": 3500, "ba ngàn rưỡi": 3500,
    "ba nghìn năm trăm": 3500, "ba ngàn năm trăm": 3500,
    "bốn nghìn": 4000, "bốn ngàn": 4000,
    "bốn nghìn rưỡi": 4500, "bốn ngàn rưỡi": 4500,
    "bốn nghìn năm trăm": 4500, "bốn ngàn năm trăm": 4500,
    "năm nghìn": 5000, "năm ngàn": 5000,
    "năm nghìn rưỡi": 5500, "năm ngàn rưỡi": 5500,
    "năm nghìn năm trăm": 5500, "năm ngàn năm trăm": 5500,
    "sáu nghìn": 6000, "sáu ngàn": 6000,
    "sáu nghìn rưỡi": 6500, "sáu ngàn rưỡi": 6500,
    "sáu nghìn năm trăm": 6500, "sáu ngàn năm trăm": 6500,
}

_LAMP_ACTION_RE = re.compile(
    r"(?<!đang )\b(?:bật|bập|thắp|tắt|mở|đóng|tăng|giảm|chỉnh|điều chỉnh|đặt|đổi|chuyển|chuyện|"
    r"sáng hơn|tối hơn|sáng lên|tối xuống|sáng thêm|tối bớt)\b",
    re.IGNORECASE,
)
_LAMP_TARGET_RE = re.compile(
    r"\b(?:đèn|đền|bóng đèn|độ sáng|sáng|tối|màu|mau|kelvin|nhiệt độ màu|"
    r"trung tính|trúng tính|vàng ấm|trắng sáng|trắng lạnh|chế độ tự động|auto mode)\b",
    re.IGNORECASE,
)
_LAMP_NEGATION_RE = re.compile(
    r"\b(?:chớ|khỏi|don't|do\s+not|never)\b|"
    r"\bđừng\s+(?!quên\b)|"
    r"\bkhông\s+(?:(?:cần|muốn|được|định)\s+)*(?:bật|bập|thắp|tắt|mở|đóng|tăng|giảm|chỉnh|điều chỉnh|đặt|đổi|chuyển|chuyện)\b",
    re.IGNORECASE,
)
_LAMP_STATUS_QUESTION_RE = re.compile(
    r"\b(?:trạng thái|bao nhiêu|là gì|màu gì|màu nào|đang bật|đang tắt|đang ở mức nào|"
    r"thế nào|ra sao|hiện tại bao nhiêu|có\s+(?:đang\s+)?(?:bật|tắt)\s+không)\b",
    re.IGNORECASE,
)
_SENSOR_QUERY_RE = re.compile(
    r"\b(?:nhiệt\s+độ(?!\s+màu)|độ\s+ẩm|ẩm\s+độ|ánh\s+sáng|lux|"
    r"bụi\s+mịn|pm2\.?5|chất\s+lượng\s+không\s+khí|không\s+khí\s+trong\s+phòng|"
    r"cảm\s+biến|hiện\s+diện|có\s+ai|có\s+người)\b",
    re.IGNORECASE,
)
_TIME_QUERY_RE = re.compile(
    r"\b(?:mấy\s+giờ|giờ\s+rồi|bây\s+giờ\s+là\s+mấy\s+giờ|"
    r"thứ\s+mấy|ngày\s+mấy|hôm\s+nay\s+là\s+(?:thứ|ngày)|ngày\s+mai\s+là\s+(?:thứ|ngày)|âm\s+lịch)\b",
    re.IGNORECASE,
)
_HARDWARE_MENTION_RE = re.compile(
    r"\b(?:đèn|đền|bóng\s+đèn|màn\s+hình|loa|âm\s+lượng|thiết\s+bị|trạng\s+thái|"
    r"cảm\s+biến|nhiệt\s+độ|độ\s+ẩm|ánh\s+sáng|bụi\s+mịn|pm2\.?5|hiện\s+diện)\b",
    re.IGNORECASE,
)


def _normalize_lamp_asr(text: str) -> str:
    """Sửa các lỗi nhận dạng giọng nói tiếng Việt phổ biến khi điều khiển đèn."""
    if not text:
        return ""
    s = text.lower()
    s = re.sub(r"\bbập\s+(đèn|đền)\b", r"bật \1", s)
    s = re.sub(r"\b(?:truyền|chuyện)\s+(?=lại|qua|sang|về|màu|mau|nhiệt\s+độ)", "chuyển ", s)
    s = re.sub(r"\bmau\b", "màu", s)
    s = re.sub(r"\btr[uú]ng\s+t[iỉĩ]nh\b", "trung tính", s)
    return s


def _format_sensor_speech(raw_text: str, user_text: str) -> str:
    """Làm tròn số thực dài và lọc đúng chỉ số cảm biến người dùng hỏi."""
    if not raw_text:
        return raw_text

    def _round_float(match: re.Match) -> str:
        val = round(float(match.group(0)), 1)
        return str(int(val)) if val.is_integer() else str(val)

    cleaned = re.sub(r"\b\d+\.\d{2,}\b", _round_float, raw_text.strip())
    cleaned = cleaned.replace("µg/m³", "microgam trên mét khối")

    q = (user_text or "").lower()
    body = re.sub(r"^phòng\s+hiện\s+tại\s*:\s*", "", cleaned, flags=re.IGNORECASE).rstrip(".")
    parts = [p.strip() for p in body.split(",") if p.strip()]

    if len(parts) > 1:
        filters = [
            (r"\bnhiệt\s+độ\b", "nhiệt độ"),
            (r"\b(?:độ\s+ẩm|ẩm\s+độ)\b", "độ ẩm"),
            (r"\b(?:bụi|pm2\.?5|không\s+khí)\b", "bụi mịn"),
            (r"\b(?:ánh\s+sáng|lux)\b", "ánh sáng"),
            (r"\b(?:hiện\s+diện|có\s+ai|có\s+người)\b", "người"),
        ]
        matched_keys = [key for pat, key in filters if re.search(pat, q)]
        if len(matched_keys) == 1:
            selected = [p for p in parts if matched_keys[0] in p.lower()]
            if selected:
                return f"Phòng hiện tại có {selected[0]}."

    return cleaned


def _requires_lamp_action_confirmation(text: str) -> bool:
    """Only guard affirmative control requests, not status questions or negations."""
    normalized = _normalize_lamp_asr(text)
    if not normalized or _LAMP_NEGATION_RE.search(normalized):
        return False
    if re.search(
        r"\bđừng\s+quên\b|\bcó\s+(?:nên|thể)\b|\blàm\s+sao\b|"
        r"\bcách\s+.+\b(?:bật|tắt|chỉnh)\b|\bở đâu\b|\bvì sao\b|\btại sao\b",
        normalized,
    ):
        return False
    if _LAMP_STATUS_QUESTION_RE.search(normalized):
        return False
    return bool(_LAMP_ACTION_RE.search(normalized) and _LAMP_TARGET_RE.search(normalized))


def _lamp_action_categories(text: str) -> set[str]:
    text = _normalize_lamp_asr(text)
    categories = set()
    has_on = bool(re.search(r"(?<!đang )\b(?:bật|bập|thắp|mở)\b", text))
    has_off = bool(re.search(r"(?<!đang )\b(?:tắt|đóng)\b", text))

    # Không nhận nhầm "trắng sáng" là chỉnh độ sáng
    text_without_color_bright = re.sub(r"\btrắng\s+sáng\b", "trắng lạnh", text)
    has_brightness = bool(re.search(
        r"\b(?:độ sáng|tăng sáng|giảm sáng|sáng hơn|tối hơn|sáng lên|tối xuống|sáng thêm|tối bớt)\b",
        text_without_color_bright,
    )) or (
        bool(re.search(r"\b(?:đặt|chỉnh|điều chỉnh|để)\b", text_without_color_bright))
        and bool(re.search(r"\b(?:độ\s+)?sáng\b", text_without_color_bright))
    )
    if has_on:
        categories.add("on")
    if has_off:
        categories.add("off")
    if has_brightness:
        categories.add("brightness")
    if has_on and has_brightness and not re.search(r"\b(?:bật|bập|thắp|mở)\s+(?:đèn|đền|bóng đèn)\b", text):
        categories.discard("on")
    if has_off and has_brightness and not re.search(r"\b(?:tắt|đóng)\s+(?:đèn|đền|bóng đèn)\b", text):
        categories.discard("off")

    vi_kelvin_pat = "|".join(map(re.escape, _VI_KELVIN_WORDS))
    if re.search(
        rf"\b(?:màu|kelvin|nhiệt độ màu|trung tính|vàng|ấm|lạnh|trắng sáng|trắng lạnh)\b|"
        rf"\b(?:\d{{4}}|{vi_kelvin_pat})\s*(?:k|ca|kelvin)\b",
        text,
    ):
        categories.add("color")
    has_auto_mode = bool(re.search(r"\b(?:chế độ tự động|auto mode)\b", text))
    if has_auto_mode:
        categories.add("auto")
        categories.discard("on")
        categories.discard("off")

    return categories or {"lamp"}


def _lamp_tool_category(tool_name: str) -> str:
    name = (tool_name or "").lower().replace("_", "").replace(".", "")
    if "turnoff" in name or "poweroff" in name:
        return "off"
    if "turnon" in name or "poweron" in name:
        return "on"
    if "brightness" in name or "dim" in name:
        return "brightness"
    if any(alias in name for alias in (
        "colortemp", "setcct", "kelvin", "color", "colour", "warmcool", "brightnesstemp",
    )):
        return "color"
    if "automode" in name or "setauto" in name:
        return "auto"
    return "lamp"


def _is_lamp_control_tool(tool_name: str) -> bool:
    """Recognize legacy Lamp.* and MCP self.lights.* control tool names."""
    name = (tool_name or "").lower().replace("_", "").replace(".", "")
    return (
        (name.startswith("lamp") or name.startswith("selflights"))
        and "getstate" not in name
    )


def _lamp_tool_categories(tool_name: str) -> set[str]:
    """Return all request categories fulfilled by a device tool."""
    normalized = (tool_name or "").lower().replace("_", "").replace(".", "")
    if "setbrightnesstemp" in normalized or "brightnessandtemp" in normalized:
        return {"brightness", "color"}
    return {_lamp_tool_category(tool_name)}


def _lamp_tool_matches_request(
    text: str,
    tool_name: str,
    required_categories: Optional[set[str]] = None,
) -> bool:
    """Check relevance only; the LLM still selects and invokes every tool."""
    if not _is_lamp_control_tool(tool_name):
        return False
    required = required_categories or _lamp_action_categories(text)
    actual = _lamp_tool_categories(tool_name)
    if len(actual) > 1 and not actual.issubset(required):
        return False
    return bool(actual & required) or "lamp" in required


def _tool_result_confirms_lamp_action(tool_name: str, arguments: dict, result: str) -> bool:
    """Require a non-error device result (JSON or plain text) before speaking success."""
    if result is None:
        return False
    normalized_name = (tool_name or "").lower().replace("_", "").replace(".", "")
    is_warm_cool_tool = "warmcool" in normalized_name
    is_brightness_temp_tool = "setbrightnesstemp" in normalized_name or "brightnessandtemp" in normalized_name
    if isinstance(result, str):
        raw = result.strip()
        if not raw:
            return False
        if raw.lower() in {"true", "ok", "success"}:
            return True
        try:
            payload = json.loads(raw)
        except ValueError:
            return False
    else:
        payload = result

    if payload is True:
        return True

    if is_brightness_temp_tool:
        if not isinstance(payload, dict) or payload.get("isError") is True or payload.get("error"):
            return False
        brightness = next((payload.get(k) for k in ("brightness_percent", "brightness", "level") if k in payload), None)
        kelvin = next((payload.get(k) for k in ("kelvin", "color_temp", "cct") if k in payload), None)
        requested_brightness = next((arguments.get(k) for k in ("brightness_percent", "brightness", "level") if k in arguments), None)
        requested_kelvin = next((arguments.get(k) for k in ("kelvin", "color_temp", "cct") if k in arguments), None)
        if None not in (brightness, kelvin, requested_brightness, requested_kelvin):
            try:
                return (
                    float(brightness) == float(requested_brightness)
                    and float(kelvin) == float(requested_kelvin)
                )
            except (TypeError, ValueError):
                return False
        return any(payload.get(key) is True for key in ("ok", "success", "succeeded"))

    if is_warm_cool_tool:
        if not isinstance(payload, dict):
            return False
        if payload.get("isError") is True or payload.get("error"):
            return False
        warm_requested = arguments.get("warm_percent")
        cool_requested = arguments.get("cool_percent")
        warm_actual = payload.get("warm_percent")
        cool_actual = payload.get("cool_percent")
        if warm_requested is not None and cool_requested is not None:
            if warm_actual is not None and cool_actual is not None:
                try:
                    return (
                        float(warm_actual) == float(warm_requested)
                        and float(cool_actual) == float(cool_requested)
                    )
                except (TypeError, ValueError):
                    return False
        return any(payload.get(key) is True for key in ("ok", "success", "succeeded"))

    if not isinstance(payload, dict):
        return False
    if payload.get("isError") is True or payload.get("error"):
        return False
    explicit_success = any(payload.get(key) is True for key in ("ok", "success", "succeeded"))
    if any(payload.get(key) is False for key in ("ok", "success", "succeeded") if key in payload):
        return False

    name = (tool_name or "").lower().replace("_", "").replace(".", "")
    if "turnon" in name or "poweron" in name:
        state = payload.get("on", payload.get("is_on"))
        if state is not None:
            return state is True
        if name.startswith("selflights"):
            try:
                warm = float(payload.get("warm_percent", 0))
                cool = float(payload.get("cool_percent", 0))
                return warm > 0 or cool > 0
            except (TypeError, ValueError):
                return False
        return explicit_success
    if "turnoff" in name or "poweroff" in name:
        state = payload.get("on", payload.get("is_on"))
        if state is not None:
            return state is False
        if name.startswith("selflights"):
            try:
                warm = float(payload.get("warm_percent", -1))
                cool = float(payload.get("cool_percent", -1))
                return warm == 0 and cool == 0
            except (TypeError, ValueError):
                return False
        return explicit_success
    if "brightness" in name or "dim" in name:
        actual = next((payload.get(k) for k in ("brightness_percent", "brightness", "level") if k in payload), None)
        requested = next((arguments.get(k) for k in ("brightness_percent", "value", "brightness", "level") if k in arguments), None)
        if actual is None or requested is None:
            return explicit_success
        try:
            return float(actual) == float(requested)
        except (TypeError, ValueError):
            return False
    if any(alias in name for alias in ("colortemp", "setcct", "kelvin", "color", "colour")):
        actual = payload.get("color_temp", payload.get("cct", payload.get("kelvin")))
        requested = next((arguments.get(k) for k in ("value", "color_temp", "cct", "kelvin") if k in arguments), None)
        if actual is None or requested is None:
            return explicit_success
        try:
            return float(actual) == float(requested)
        except (TypeError, ValueError):
            return False
    if "automode" in name or "setauto" in name:
        actual = payload.get("auto_mode", payload.get("auto", payload.get("enabled")))
        requested = next((arguments.get(k) for k in ("enabled", "value", "auto") if k in arguments), True)
        return isinstance(actual, bool) and actual is requested
    return False


_VI_UNIT_NUMBERS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "tư": 4,
    "bốn": 4, "năm": 5, "lăm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
}
_VI_TENS = {
    "mười": 10, "hai mươi": 20, "ba mươi": 30, "bốn mươi": 40,
    "năm mươi": 50, "sáu mươi": 60, "bảy mươi": 70,
    "tám mươi": 80, "chín mươi": 90,
}


def _parse_requested_number(text: str, *, percent: bool = False) -> Optional[int]:
    """Parse a clear digit or Vietnamese number phrase from a lamp command."""
    suffix = r"(?:\s*%|\s+phần\s+trăm\b)" if percent else r"\s*(?:k|ca|kelvin)\b"
    digit_match = re.search(rf"(?<!\d)(\d{{1,4}}){suffix}", text, re.IGNORECASE)
    if digit_match:
        value = int(digit_match.group(1))
        return value if (not percent or 0 <= value <= 100) else None

    if not percent:
        return None
    number_words = "|".join(sorted(map(re.escape, _VI_TENS), key=len, reverse=True))
    units = "|".join(sorted(map(re.escape, _VI_UNIT_NUMBERS), key=len, reverse=True))
    word_match = re.search(
        rf"\b(?P<tens>{number_words})(?:\s+(?P<unit>{units}))?\s+phần\s+trăm\b|"
        rf"\b(?P<unit_only>{units})\s+phần\s+trăm\b",
        text,
        re.IGNORECASE,
    )
    if not word_match:
        return None
    if word_match.group("tens"):
        value = _VI_TENS[word_match.group("tens").lower()]
        if word_match.group("unit"):
            value += _VI_UNIT_NUMBERS[word_match.group("unit").lower()]
    else:
        value = _VI_UNIT_NUMBERS[word_match.group("unit_only").lower()]
    return value if 0 <= value <= 100 else None


def _lamp_tool_name(tool: dict) -> str:
    function = tool.get("function") or {}
    return str(function.get("name") or tool.get("name") or "")


def _lamp_color_request(text: str) -> Optional[tuple[str, int]]:
    """Return a normalized color label and Kelvin value for explicit color phrases."""
    lowered = _normalize_lamp_asr(text)
    if re.search(r"\b(?:trung\s+tính|ánh\s+sáng\s+tự\s+nhiên)\b", lowered):
        return "trung tính", 4500
    if re.search(r"\b(?:vàng\s+ấm|ấm|vàng)\b", lowered):
        return "vàng ấm", 3000
    if re.search(r"\b(?:trắng\s+lạnh|trắng\s+sáng|lạnh)\b", lowered):
        return "trắng lạnh", 6000

    kelvin_match = re.search(
        r"(?<!\d)(\d{4})\s*(?:k|ca|kelvin)\b",
        lowered,
        re.IGNORECASE,
    )
    if kelvin_match:
        kelvin = min(6000, max(3000, int(kelvin_match.group(1))))
        label = "vàng ấm" if kelvin < 3750 else "trung tính" if kelvin < 5250 else "trắng lạnh"
        return label, kelvin

    for phrase, kelvin in sorted(_VI_KELVIN_WORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\s*(?:k|ca|kelvin)?\b", lowered):
            clamped = min(6000, max(3000, kelvin))
            label = "vàng ấm" if clamped < 3750 else "trung tính" if clamped < 5250 else "trắng lạnh"
            return label, clamped

    return None


def _lamp_tool_arguments(tool: dict, text: str) -> Optional[dict]:
    """Create arguments only where the request and this device's schema are explicit."""
    name = _lamp_tool_name(tool)
    normalized = name.lower().replace("_", "").replace(".", "")
    function = tool.get("function") or {}
    schema = function.get("parameters") or {}
    properties = schema.get("properties") or {}
    args: dict = {}

    if "setbrightnesstemp" in normalized or "brightnessandtemp" in normalized:
        brightness = _parse_requested_number(text, percent=True)
        color = _lamp_color_request(text)
        if brightness is None or color is None:
            return None
        brightness_key = next((key for key in ("brightness_percent", "brightness", "level") if key in properties), None)
        kelvin_key = next((key for key in ("kelvin", "color_temp", "cct") if key in properties), None)
        if brightness_key is None or kelvin_key is None:
            return None
        args = {brightness_key: brightness, kelvin_key: color[1]}
    elif "warmcool" in normalized:
        color = _lamp_color_request(text)
        if color is None:
            return None
        kelvin = color[1]
        warm = round((6000 - kelvin) / 30)
        args = {"warm_percent": warm, "cool_percent": 100 - warm}
    elif "turnon" in normalized or "poweron" in normalized or "turnoff" in normalized or "poweroff" in normalized:
        args = {}
    elif "brightness" in normalized or "dim" in normalized:
        brightness = _parse_requested_number(text, percent=True)
        if brightness is None:
            return None
        key = next((key for key in ("brightness_percent", "value", "brightness", "level") if key in properties), None)
        if key is None:
            return None
        args[key] = brightness
    elif _lamp_tool_category(name) == "color":
        color = _lamp_color_request(text)
        if color is None:
            return None
        key = next((key for key in ("kelvin", "color_temp", "cct", "value") if key in properties), None)
        if key is None:
            return None
        args[key] = color[1]
        prop = properties.get(key) or {}
        if key == "value" and prop.get("maximum", 100) <= 100:
            args[key] = round((color[1] - 3000) / 30)
    elif "automode" in normalized or "setauto" in normalized:
        if "enabled" not in properties and "value" not in properties and "auto" not in properties:
            return None
        enabled = not bool(re.search(r"\b(?:tắt|hủy|huỷ|ngừng)\b", text.lower()))
        key = next((key for key in ("enabled", "value", "auto") if key in properties), None)
        args[key] = enabled
    else:
        return None

    if _validate_tool_arguments(schema, args):
        return None
    return args


def _build_lamp_control_plan(text: str, tools: list) -> Optional[tuple[list[tuple[str, dict]], str]]:
    """Build a deterministic MCP plan for clear lamp commands; leave ambiguous speech to the LLM."""
    if not _requires_lamp_action_confirmation(text) or not tools:
        return None

    required = _lamp_action_categories(text)
    if not required or "lamp" in required:
        return None
    candidates = [t for t in tools if isinstance(t, dict) and _is_lamp_control_tool(_lamp_tool_name(t))]
    if not candidates:
        return None

    color = _lamp_color_request(text) if "color" in required else None
    if "color" in required and color is None:
        return None
    if "brightness" in required and _parse_requested_number(text, percent=True) is None:
        return None

    plans: list[tuple[str, dict]] = []
    handled: set[str] = set()

    if {"brightness", "color"}.issubset(required):
        combined = next((
            t for t in candidates
            if ("setbrightnesstemp" in _lamp_tool_name(t).lower().replace("_", "").replace(".", ""))
            and _lamp_tool_matches_request(text, _lamp_tool_name(t), required)
        ), None)
        if combined is not None:
            args = _lamp_tool_arguments(combined, text)
            if args is not None:
                plans.append((_lamp_tool_name(combined), args))
                handled.update({"brightness", "color"})

    for category in ("on", "off", "brightness", "color", "auto"):
        if category not in required or category in handled:
            continue
        if category == "on":
            action_aliases = ("turnon", "poweron")
        elif category == "off":
            action_aliases = ("turnoff", "poweroff")
        elif category == "brightness":
            action_aliases = ("setbrightness", "setlevel", "dim")
        elif category == "color":
            action_aliases = ("setwarmcool", "setcolortemp", "setcct", "setkelvin", "setcolor")
        else:
            action_aliases = ("setautomode", "automode")
        matching = [
            t for t in candidates
            if category in _lamp_tool_categories(_lamp_tool_name(t))
            and any(alias in _lamp_tool_name(t).lower().replace("_", "").replace(".", "") for alias in action_aliases)
            and _lamp_tool_matches_request(text, _lamp_tool_name(t), required)
        ]
        if category == "color":
            matching.sort(key=lambda t: 0 if "warmcool" in _lamp_tool_name(t).lower().replace("_", "") else 1)
        selected = next((
            (t, args) for t in matching
            if (args := _lamp_tool_arguments(t, text)) is not None
        ), None)
        if selected is None:
            return None
        tool, args = selected
        plans.append((_lamp_tool_name(tool), args))
        handled.add(category)

    if handled != required or not plans:
        return None

    response_parts = []
    if "on" in required:
        response_parts.append("Mình đã bật đèn")
    if "off" in required:
        response_parts.append("Mình đã tắt đèn")
    if "brightness" in required:
        brightness = _parse_requested_number(text, percent=True)
        response_parts.append(f"đặt độ sáng {brightness} phần trăm")
    if "color" in required and color:
        response_parts.append(f"chuyển màu sang {color[0]}")
    if "auto" in required:
        enabled = any(args.get("enabled", args.get("value", args.get("auto", True))) for name, args in plans if "auto" in _lamp_tool_categories(name))
        response_parts.append("bật chế độ tự động" if enabled else "tắt chế độ tự động")

    power_action = "bật đèn" if "on" in required else "tắt đèn" if "off" in required else None
    details = []
    if "brightness" in required:
        brightness = _parse_requested_number(text, percent=True)
        details.append(f"đặt độ sáng {brightness} phần trăm")
    if "color" in required and color:
        details.append(f"chuyển màu sang {color[0]}")
    if "auto" in required:
        details.append(response_parts[-1])

    if power_action:
        response = f"Mình đã {power_action}"
        if details:
            response += " và " + " và ".join(details)
    else:
        response = "Mình đã " + " và ".join(details or response_parts)
    return plans, response + "."


def _validate_tool_arguments(schema: dict, arguments: dict) -> Optional[str]:
    """Validate the common JSON Schema constraints used by MCP tools."""
    if not isinstance(arguments, dict):
        return "arguments phải là object"
    if not isinstance(schema, dict):
        return None

    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        return f"thiếu tham số bắt buộc: {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        unknown = [key for key in arguments if key not in properties]
        if unknown:
            return f"tham số không được hỗ trợ: {', '.join(unknown)}"

    expected_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key, value in arguments.items():
        prop_schema = properties.get(key, {})
        expected = prop_schema.get("type") if isinstance(prop_schema, dict) else None
        if isinstance(expected, list):
            accepted = [expected_types[t] for t in expected if isinstance(t, str) and t in expected_types]
            py_type = tuple(
                cls for group in accepted
                for cls in (group if isinstance(group, tuple) else (group,))
            ) or None
        else:
            py_type = expected_types.get(expected) if isinstance(expected, str) else None
        if py_type and (not isinstance(value, py_type) or (expected == "integer" and isinstance(value, bool))):
            return f"tham số {key} phải có kiểu {expected}"
        if isinstance(prop_schema, dict):
            if "enum" in prop_schema and value not in prop_schema["enum"]:
                return f"tham số {key} không thuộc enum cho phép"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in prop_schema and value < prop_schema["minimum"]:
                    return f"tham số {key} nhỏ hơn giới hạn"
                if "maximum" in prop_schema and value > prop_schema["maximum"]:
                    return f"tham số {key} lớn hơn giới hạn"
    return None


def _denoise_wav_16k(wav_bytes: bytes) -> bytes:
    """Khử nhiễu file WAV PCM16 16kHz mono bằng DeepFilterNet3."""
    if not config._get("denoiser", "enabled", default=True):
        return wav_bytes
    try:
        from app.core.utils.df3_denoiser import DeepFilterNet3StreamDenoiser

        atten_lim = float(config._get("denoiser", "atten_lim_db", default=18.0))
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            if (
                wf.getnchannels() != 1
                or wf.getsampwidth() != 2
                or wf.getframerate() != 16000
            ):
                return wav_bytes
            raw_pcm = wf.readframes(wf.getnframes())

        denoiser = DeepFilterNet3StreamDenoiser(atten_lim_db=atten_lim)
        cleaned_pcm = denoiser.process_pcm16_16k(raw_pcm, flush_end=True)
        if not cleaned_pcm:
            return wav_bytes

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as out_wf:
            out_wf.setnchannels(1)
            out_wf.setsampwidth(2)
            out_wf.setframerate(16000)
            out_wf.writeframes(cleaned_pcm)
        return out_buf.getvalue()
    except Exception:
        return wav_bytes


def _is_device_tool(tool: dict) -> bool:
    if not isinstance(tool, dict):
        return False
    name = str((tool.get("function") or {}).get("name") or tool.get("name") or "")
    return name.startswith(("self.", "Lamp.", "Screen.", "Sensor.", "Speaker.", "Audio."))


def _prune_irrelevant_device_tools(tools: list, user_text: str) -> list:
    """Loại bỏ device tools khi câu hỏi chỉ dùng server tool (thời tiết, tin tức, lịch, nhạc)."""
    if not tools or not user_text:
        return tools
    has_server_tool = any(not _is_device_tool(t) for t in tools)
    if not has_server_tool:
        return tools
    if _HARDWARE_MENTION_RE.search(user_text):
        return tools
    return [t for t in tools if not _is_device_tool(t)]


class ConnectionHandler:
    def __init__(self, ws: WebSocket, session_id: int, device_id: str):
        self.ws = ws
        self.session_id = session_id
        self.device_id = device_id
        self.log = get_session_logger(session_id, device_id)

        self.dialogue = Dialogue()
        self._init_providers()

        self._pipeline_task: Optional[asyncio.Task] = None
        self._background_tasks: set[asyncio.Task] = set()
        self._quick_tts_task: Optional[asyncio.Task] = None
        self._closed = False

        self._pending_calendar = None
        self._reset_turn_state()
        self._music_playing = False

    def _reset_turn_state(self, keep_user_wav: bool = False):
        user_wav = self._captured.get("user_wav") if keep_user_wav else None
        self._captured = {
            "user_wav": user_wav,
            "bot_mp3_parts": [],
        }
        self._pending_music = None
        self._end_sent = False
        self._close_after_end = False

    @property
    def transport(self):
        """Alias tương thích — transport được lưu ở ``self.ws``."""
        return self.ws

    async def _stop_audio(self):
        # Base no-op. ESP32ConnectionHandler override.
        pass

    async def notify_reminder(self, reminder: dict) -> None:
        if self._music_playing:
            self._music_playing = False
            try:
                await self._stop_audio()
            except Exception as e:
                self.log.debug(f"Dừng nhạc khi nhắc hẹn lỗi: {e}")

        text = reminder["text"]
        audio = await self.tts.synthesize(text)
        if not audio:
            raise RuntimeError("TTS empty")
        await self._send_callback({
            "type": "audio",
            "index": 1,
            "total": 1,
            "sentence": text,
            "reminder_id": reminder.get("reminder_id", reminder.get("id")),
            "data": audio,
        })
        await self._send_callback({"type": "tts_stop"})

    def _init_providers(self):
        from app.core.runtime import get_runtime
        runtime = get_runtime()

        if runtime is not None:
            self.asr = runtime.asr
            self.llm = runtime.llm
            self.tts = runtime.tts
            self.tool_handler = runtime.tool_handler
        else:
            self._init_local_providers()
            self.tool_handler = UnifiedToolHandler(log=self.log)

        self.tool_handler.set_display_callback(self._notify_tool_display)

        self.memory = ProviderRegistry.create_memory(
            config.memory_provider,
            config={"max_turns": config.memory_max_turns},
            log=self.log,
        )

        intent_mode = config.intent_provider
        if intent_mode == "intent_llm":
            self.intent_provider = IntentLLMProvider(log=self.log)
        elif intent_mode == "nointent":
            self.intent_provider = NoIntentProvider()
        else:
            self.intent_provider = FunctionCallIntentProvider()

    def _init_local_providers(self):
        self.asr = ProviderRegistry.create_asr(
            config.asr_provider,
            config={
                "url": config.asr_url,
                "model": config.asr_model,
                "language": config.asr_language,
                "request_timeout": config.asr_request_timeout,
            },
            log=self.log,
        )

        self.llm = ProviderRegistry.create_llm(
            config.llm_provider,
            config={
                "url": config.llm_url,
                "model": config.llm_model,
                "temperature": config.llm_temperature,
                "num_predict": config.llm_num_predict,
                "max_tool_iterations": config.llm_max_tool_iterations,
                "request_timeout": config.llm_request_timeout,
                "think": config.llm_think,
                "num_ctx": config.llm_num_ctx,
                "num_batch": config.llm_num_batch,
                "keep_alive": config.llm_keep_alive,
            },
            tools_schema=TOOLS_SCHEMA,
            log=self.log,
        )

        self.tts = ProviderRegistry.create_tts(
            config.tts_provider,
            config={
                "voice": config.tts_voice,
                "rate": config.tts_rate,
                "volume": config.tts_volume,
                "request_timeout": config.tts_request_timeout,
                "max_retries": config.tts_max_retries,
                "url": config.tts_vieneu_url,
                "edge_voice": config.tts_edge_voice,
                "piper_model": config.tts_piper_model,
                "piper_binary": config.tts_piper_binary,
            },
            log=self.log,
        )

    async def _notify_tool_display(self, tool_name: str):
        """Gửi thông báo tool đang được gọi xuống client."""
        try:
            await self._send_callback({"type": "tool", "name": tool_name})
        except Exception as e:
            self.log.debug(f"Notify tool display lỗi: {e}")

    async def abort(self):
        self._closed = True
        for task in tuple(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        task = self._pipeline_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._pipeline_task = None
        self._captured["bot_mp3_parts"] = []

    async def _emit_token(
        self,
        text: str,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """Gửi token text xuống client và kích hoạt hook tách câu TTS nếu có."""
        if not text:
            return
        if on_token is not None:
            await on_token(text)
        await self._send_callback({"type": "token", "content": text})

    def _get_device_state_context(self) -> str:
        """Lấy trạng thái đèn/cảm biến thực tế từ DeviceHub để tiêm vào system_prompt."""
        try:
            from app.core.device_hub import get_device_hub

            lamp = get_device_hub().get_lamp(device_id=self.device_id)
            if not lamp:
                return ""
            return (
                f"\n[Trạng thái phần cứng thực tế hiện tại ({self.device_id})]: "
                f"on={lamp.get('on')}, brightness={lamp.get('brightness')}, cct={lamp.get('cct')}."
            )
        except Exception:
            return ""

    async def _summarize_tool_payload(
        self,
        messages: list,
        tool_name: str,
        tool_args: dict,
        result_text: str,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Cho LLM tóm tắt kết quả từ tool thiết bị (Action.REQLLM) mà không truyền thêm tools."""
        call_id = "det_0"
        follow_messages = list(messages) + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tool_args},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": _compact_tool_result(result_text, max_chars=600),
            },
            {
                "role": "system",
                "content": "Trả lời ngắn gọn 1-2 câu tiếng Việt tự nhiên dựa trên dữ liệu thiết bị vừa nhận; không gọi thêm tool.",
            },
        ]
        parts = []
        async for event in self.llm.response_with_functions(follow_messages, tools=[]):
            if event.get("type") == "token":
                tok = event.get("content", "")
                if tok:
                    parts.append(tok)
                    await self._emit_token(tok, on_token=on_token)
        return _clean_response("".join(parts).strip())

    async def handle_text(self, user_text: str) -> str:
        self.log.info(f"👤 User: {user_text}")
        self._end_sent = False
        self._close_after_end = False
        self._pending_music = None

        if _FAREWELL_RE.fullmatch(_norm(user_text)):
            self._close_after_end = True
            reply = "Tạm biệt bạn nhé. Mình dừng lắng nghe đây, cần gì cứ gọi mình nha."
            return await self._quick_response(user_text, reply)

        pending_calendar = self._pending_calendar
        if pending_calendar:
            normalized = " ".join(user_text.strip().lower().split()).strip(".!? ")
            if normalized in {"xác nhận", "đồng ý", "đồng ý nhé", "có", "ừ", "vâng", "ok", "okay"}:
                from app.core.providers.tools.calendar import execute_pending
                response = await execute_pending(self, pending_calendar.get("token"))
                return await self._quick_response(user_text, response)
            if normalized in {"hủy", "huỷ", "không", "thôi", "bỏ qua", "không cần"}:
                self._pending_calendar = None
                return await self._quick_response(user_text, "Ừ, mình hủy đề xuất lịch này nhé.")
            self._pending_calendar = None

        # 1. FAST TRACK
        injected_context = None
        try:
            fast = await process_fast_track(
                user_text,
                self._quick_response,
                self.log,
                execute_tool=lambda name, args: self.tool_handler.execute(self, name, args),
            )
            if isinstance(fast, dict) and "__llm_context__" in fast:
                injected_context = fast["__llm_context__"]
            elif fast is not None:
                return fast
        except Exception as e:
            self.log.debug(f"fast_track lỗi (bỏ qua): {e}")

        # 2. LLM + TTS PIPELINE
        self.dialogue.append_user(user_text)
        self._captured["bot_mp3_parts"] = []

        now = _dt.now(_VN_TZ)
        weekday_vi = _WEEKDAYS_VI[now.weekday()]
        device_ctx = self._get_device_state_context()
        sys_prompt = (
            f"{config.system_prompt}\n"
            "Nhịp điệu hội thoại: Nói tự nhiên, nhẹ nhàng, thân thiện như người bạn; thường 1-2 câu ngắn, "
            "không rập khuôn đầu câu. Khi người dùng chia sẻ cảm xúc, đồng cảm ngắn gọn trước khi gợi ý tiếp; "
            "chỉ gọi tool khi có ý định rõ ràng và không suy đoán khi thiếu ngữ cảnh.\n"
            f"[Thời gian hiện tại (UTC+7): {now.strftime('%H:%M')} {weekday_vi}, ngày {now.strftime('%Y-%m-%d')}]"
            f"{device_ctx}"
        )
        if injected_context:
            sys_prompt += (
                f"\n\n[DỮ LIỆU LỊCH HỆ THỐNG]:\n{injected_context}\n"
                "Trả lời trực tiếp bằng 1-2 câu tiếng Việt tự nhiên, dễ nghe qua loa; không gọi thêm tool."
            )

        messages = self.dialogue.to_llm_messages(
            memory_str=None,
            system_prompt=sys_prompt,
            max_turns=config.llm_history_keep * 2,
        )

        tools = [] if injected_context else _prune_irrelevant_device_tools(
            build_tool_schema(user_text, device_id=self.device_id, log=self.log),
            user_text,
        )
        await set_ai_visual_state("thinking", self.log)
        self._pipeline_task = asyncio.create_task(
            self._stream_llm_tts(messages, tools=tools, skip_intent=bool(injected_context))
        )
        try:
            full_response = await self._pipeline_task
        except asyncio.CancelledError:
            self.log.info("⏹️ Pipeline bị cancel")
            raise
        finally:
            self._pipeline_task = None

        full_response = _clean_response(full_response)
        self.dialogue.append_assistant(full_response)
        await self.memory.save(str(self.session_id), [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_response},
        ])
        return full_response

    async def handle_voice(self, audio_bytes: bytes) -> Optional[str]:
        try:
            wav = await any_to_wav(audio_bytes, sample_rate=config.sample_rate)
            wav = await asyncio.to_thread(_denoise_wav_16k, wav)
            self.log.info(f"🎵 Audio: {len(audio_bytes)} → WAV {len(wav)}b")
        except Exception as e:
            self.log.error(f"❌ Convert audio lỗi: {e}")
            await self._send_error(f"Lỗi audio: {e}")
            return None
        return await self.handle_voice_wav(wav)

    async def handle_voice_wav(self, wav_bytes: bytes) -> Optional[str]:
        self._reset_turn_state(keep_user_wav=False)
        self._captured["user_wav"] = wav_bytes
        await self._send_callback({"type": "user_wav", "data": wav_bytes})
        await self._send_callback({"type": "status", "text": "Đang nghe..."})
        await set_ai_visual_state("listening", self.log)

        from app.core.utils.audio_metrics import summarize_pcm16_mono

        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
                pcm = wav_file.readframes(wav_file.getnframes())
                sample_rate = wav_file.getframerate()
            audio_metrics = summarize_pcm16_mono(pcm, sample_rate)
            self.log.info(f"🎚️ ASR input metrics: {audio_metrics}")
            if isinstance(audio_metrics, dict) and audio_metrics.get("peak_dbfs", 0.0) < -24.0:
                self.log.info("🔇 Bỏ qua audio mức tín hiệu quá nhỏ (nhiễu nền/echo)")
                return None
        except Exception:
            self.log.debug("ASR input metrics unavailable (invalid WAV header)")

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        if user_text:
            self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")
        else:
            self.log.warning(f"📝 ASR empty [{elapsed:.0f}ms]")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)

    async def chat_with_tools(
        self,
        messages: list,
        tools: list,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        skip_intent: bool = False,
    ) -> str:
        """Tool loop: Intent router + Native tool calling."""
        max_iter = max(1, int(config.llm_max_tool_iterations))
        current_messages = list(messages)

        domain = "chat"
        intent_result = None
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        music_req = is_music_request(last_user)

        # 1. Deterministic điều khiển đèn (nhanh & chính xác tuyệt đối)
        require_lamp_tool = _requires_lamp_action_confirmation(last_user)
        if require_lamp_tool:
            lamp_plan = _build_lamp_control_plan(last_user, tools or [])
            if lamp_plan is not None:
                planned_calls, planned_response = lamp_plan
                self.log.info(f"⚡ Deterministic lamp plan: {[name for name, _ in planned_calls]}")
                for name, arguments in planned_calls:
                    self.log.info(f"Tool call (deterministic): {name}({arguments})")
                    action_resp = await self.tool_handler.execute(self, name, arguments)
                    result_text = str(action_resp.result or action_resp.response or "")
                    if (
                        action_resp.action != Action.REQLLM
                        or not _tool_result_confirms_lamp_action(name, arguments, result_text)
                    ):
                        final_text = "Mình chưa thể xác nhận đã điều khiển được đèn. Bạn thử lại giúp mình nhé."
                        await self._emit_token(final_text, on_token=on_token)
                        return final_text
                    self.log.info(f"✅ Device action confirmed by MCP result: {name}")
                await self._emit_token(planned_response, on_token=on_token)
                return planned_response

        # 2. Deterministic hỏi giờ / ngày / thứ / âm lịch
        if not skip_intent and not require_lamp_tool and _TIME_QUERY_RE.search(last_user):
            time_tool = next(
                (
                    (t.get("function") or {}).get("name")
                    for t in (tools or [])
                    if isinstance(t, dict)
                    and (t.get("function") or {}).get("name") == "get_current_time"
                ),
                None,
            )
            if time_tool:
                self.log.info(f"⚡ Deterministic time read: {time_tool}")
                action_resp = await self.tool_handler.execute(self, time_tool, {})
                if action_resp.action in (Action.RESPONSE, Action.RECORD):
                    final_text = _clean_response(str(action_resp.response or action_resp.result).strip())
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
                if action_resp.action == Action.REQLLM and action_resp.result:
                    final_text = await self._summarize_tool_payload(
                        current_messages, time_tool, {}, str(action_resp.result), on_token=on_token,
                    )
                    if final_text:
                        return final_text
            now = _dt.now(_VN_TZ)
            weekday_vi = _WEEKDAYS_VI[now.weekday()]
            final_text = f"Bây giờ là {now.strftime('%H:%M')} {weekday_vi}, ngày {now.strftime('%d/%m/%Y')}."
            await self._emit_token(final_text, on_token=on_token)
            return final_text

        # 3. Deterministic đọc cảm biến (lọc đúng chỉ số hỏi & làm tròn số lẻ)
        if not skip_intent and not require_lamp_tool and _SENSOR_QUERY_RE.search(last_user):
            sensor_tool = next(
                (
                    (t.get("function") or {}).get("name")
                    for t in (tools or [])
                    if isinstance(t, dict)
                    and (t.get("function") or {}).get("name") in {
                        "get_sensor", "get_air_quality", "Sensor.Read", "self.get_environment",
                    }
                ),
                None,
            )
            if sensor_tool:
                self.log.info(f"⚡ Deterministic sensor read: {sensor_tool}")
                action_resp = await self.tool_handler.execute(self, sensor_tool, {})
                raw_sensor = str(action_resp.response or action_resp.result or "").strip()
                if action_resp.action in (Action.RESPONSE, Action.RECORD) and raw_sensor:
                    final_text = _clean_response(_format_sensor_speech(raw_sensor, last_user))
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
                if action_resp.action == Action.REQLLM and raw_sensor:
                    try:
                        data = json.loads(raw_sensor)
                        if isinstance(data, dict):
                            q = last_user.lower()
                            if re.search(r"\bnhiệt\s+độ\b", q) and "temperature" in data:
                                val = round(float(data["temperature"]), 1)
                                final_text = f"Nhiệt độ phòng hiện tại khoảng {int(val) if val.is_integer() else val} độ."
                                await self._emit_token(final_text, on_token=on_token)
                                return final_text
                            if re.search(r"\b(?:độ\s+ẩm|ẩm\s+độ)\b", q) and "humidity" in data:
                                val = round(float(data["humidity"]), 1)
                                final_text = f"Độ ẩm phòng hiện tại là {int(val) if val.is_integer() else val} phần trăm."
                                await self._emit_token(final_text, on_token=on_token)
                                return final_text
                    except (ValueError, TypeError):
                        pass

                    final_text = await self._summarize_tool_payload(
                        current_messages, sensor_tool, {}, raw_sensor, on_token=on_token,
                    )
                    if final_text:
                        return final_text

        # 4. Deterministic hỏi trạng thái đèn / thiết bị
        if not skip_intent and not require_lamp_tool and _LAMP_STATUS_QUESTION_RE.search(last_user) and re.search(
            r"\b(?:đèn|đền|bóng\s+đèn|thiết\s+bị)\b", last_user, re.IGNORECASE,
        ):
            state_tool = next(
                (
                    (t.get("function") or {}).get("name")
                    for t in (tools or [])
                    if isinstance(t, dict)
                    and (t.get("function") or {}).get("name") in {"Lamp.GetState", "self.get_device_status"}
                ),
                None,
            )
            if state_tool:
                self.log.info(f"⚡ Deterministic state read: {state_tool}")
                action_resp = await self.tool_handler.execute(self, state_tool, {})
                result_raw = str(action_resp.result or action_resp.response or "").strip()
                if result_raw:
                    final_text = await self._summarize_tool_payload(
                        current_messages, state_tool, {}, result_raw, on_token=on_token,
                    )
                    if final_text:
                        return final_text

        if not skip_intent and isinstance(self.intent_provider, IntentLLMProvider):
            if require_lamp_tool:
                self.log.info("⏩ Skip intent model for explicit lamp control")
            elif music_req:
                self.log.info(f"⏩ Skip intent (music request): {last_user[:40]!r}")
            elif looks_like_pure_chat(last_user):
                self.log.info(f"⏩ Skip intent (pure chat): {last_user[:40]!r}")
            else:
                try:
                    intent_result = await self.intent_provider.detect_intent_full(self, last_user)
                    if intent_result and intent_result.intent:
                        domain = intent_result.intent
                except Exception as e:
                    self.log.warning(f"⚠️ Intent lỗi (fallback chat): {e}")

        self.log.info(f"🎯 Intent Domain: {domain}")

        if not skip_intent and intent_result and intent_result.tool and not intent_result.needs_args:
            self.log.info(f"⚡ Fastpath: {intent_result.tool} (no args)")
            try:
                tool_args = {}
                if intent_result.tool == "get_sensor":
                    text_lower = last_user.lower()
                    if any(term in text_lower for term in ("độ ẩm", "ẩm độ")):
                        tool_args = {"sensor": "humidity"}
                    elif any(term in text_lower for term in ("ánh sáng", "lux")):
                        tool_args = {"sensor": "light_lux"}
                    elif any(term in text_lower for term in ("nhiệt độ", "nóng", "lạnh")):
                        tool_args = {"sensor": "temperature"}
                    elif any(term in text_lower for term in ("bụi", "pm2", "pm25")):
                        tool_args = {"sensor": "pm25"}
                    elif any(term in text_lower for term in ("hiện diện", "có ai", "có người")):
                        tool_args = {"sensor": "presence"}
                    else:
                        tool_args = {"sensor": "all"}
                action_resp = await self.tool_handler.execute(
                    self, intent_result.tool, tool_args,
                )
                if action_resp.action in (Action.RESPONSE, Action.RECORD):
                    raw_res = str(action_resp.response or action_resp.result).strip()
                    if intent_result.tool == "get_sensor":
                        raw_res = _format_sensor_speech(raw_res, last_user)
                    final_text = _clean_response(raw_res)
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
                if action_resp.action == Action.ERROR:
                    final_text = "Mình không thực hiện được yêu cầu lúc này."
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
            except Exception as e:
                self.log.warning(f"⚡ Fastpath lỗi: {e} — fallback LLM")

        if not skip_intent and isinstance(self.intent_provider, IntentLLMProvider):
            if domain != "chat":
                rebuilt = build_tool_schema(
                    last_user, domain=domain, device_id=self.device_id, log=self.log,
                )
                if rebuilt:
                    tools = _prune_irrelevant_device_tools(rebuilt, last_user)

        required_lamp_categories = _lamp_action_categories(last_user) if require_lamp_tool else set()
        confirmed_lamp_categories: set[str] = set()
        attempted_lamp_categories: set[str] = set()
        available_lamp_categories = {
            category
            for t in (tools or [])
            if isinstance(t, dict)
            and _is_lamp_control_tool(
                str((t.get("function") or {}).get("name") or t.get("name", ""))
            )
            for category in _lamp_tool_categories(
                str((t.get("function") or {}).get("name") or t.get("name", ""))
            )
        }
        if "lamp" in required_lamp_categories and any(
            isinstance(t, dict)
            and _is_lamp_control_tool(
                str((t.get("function") or {}).get("name") or t.get("name", ""))
            )
            for t in (tools or [])
        ):
            available_lamp_categories.add("lamp")
        unsupported_lamp_categories = required_lamp_categories - available_lamp_categories
        if require_lamp_tool and unsupported_lamp_categories:
            final_text = "Thiết bị chưa cung cấp đủ công cụ để thực hiện toàn bộ yêu cầu điều khiển đèn."
            await self._emit_token(final_text, on_token=on_token)
            return final_text

        for iteration in range(max_iter):
            token_parts = []
            tool_calls = []
            prebuffer = ""
            prebuffered = 0
            flushed = False
            hold_tokens = require_lamp_tool
            PREFETCH_TOKENS = 15

            async for event in self.llm.response_with_functions(current_messages, tools=tools):
                etype = event.get("type")
                if etype == "token":
                    tok = event.get("content", "")
                    if not tok:
                        continue
                    token_parts.append(tok)
                    if not tool_calls:
                        if hold_tokens or not flushed:
                            prebuffer += tok
                            prebuffered += 1
                            if not hold_tokens and prebuffered >= PREFETCH_TOKENS:
                                flushed = True
                                await self._emit_token(prebuffer, on_token=on_token)
                                prebuffer = ""
                        else:
                            await self._emit_token(tok, on_token=on_token)
                elif etype == "tool_call":
                    tool_calls.append(event)
                    prebuffer = ""

            if not tool_calls:
                if hold_tokens and not required_lamp_categories.issubset(confirmed_lamp_categories):
                    if iteration + 1 < max_iter:
                        self.log.warning("⚠️ LLM bỏ qua tool ở lượt điều khiển đèn — thử lại")
                        tool_specs = []
                        matching_tool_names = set()
                        for t in (tools or []):
                            fn = t.get("function") or {}
                            tname = fn.get("name") or t.get("name", "")
                            props = (fn.get("parameters") or {}).get("properties") or {}
                            if tname and _lamp_tool_matches_request(
                                last_user, tname, required_lamp_categories,
                            ):
                                matching_tool_names.add(tname.lower())
                                param_desc = ", ".join(
                                    f'"{k}": <{v.get("type", "integer")}>'
                                    for k, v in props.items()
                                )
                                tool_specs.append(f"{tname}({{{param_desc}}})")
                        guidance = []
                        if any("set_warm_cool" in name for name in matching_tool_names):
                            guidance.append(
                                "Với set_warm_cool, vàng ấm là warm_percent=100/cool_percent=0, "
                                "trung tính là 50/50, trắng lạnh là 0/100; mỗi giá trị 0-100."
                            )
                        if any("set_brightness_temp" in name for name in matching_tool_names):
                            guidance.append(
                                "Với set_brightness_temp, truyền brightness_percent 0-100 và kelvin "
                                "3000-6000 (3000 ấm, 4500 trung tính, 6000 lạnh)."
                            )
                        current_messages.append({
                            "role": "system",
                            "content": (
                                f"BẮT BUỘC gọi đúng tool phù hợp ngay: {' hoặc '.join(tool_specs)}. "
                                + " ".join(guidance)
                                + " Chuyển số tiếng Việt thành số nguyên; chỉ xuất tool_call, không xuất văn bản."
                            ),
                        })
                        continue
                    final_text = "Mình chưa thể xác nhận đã điều khiển được đèn. Bạn thử lại giúp mình nhé."
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text

                if not flushed and prebuffer:
                    await self._emit_token(prebuffer, on_token=on_token)
                return _clean_response("".join(token_parts).strip())

            assistant_calls = []
            normalized_calls = []
            for index, tc in enumerate(tool_calls):
                call_id = tc.get("id") or f"xiaozhi_{iteration}_{index}"
                name = tc.get("name") or ""
                raw_args = tc.get("arguments", {})
                parsed_args = raw_args
                parse_error = None
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args or "{}")
                    except (TypeError, ValueError) as exc:
                        parsed_args = {}
                        parse_error = f"arguments JSON không hợp lệ: {exc}"
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
                    parse_error = parse_error or "arguments phải là object"

                tool_entry = next(
                    (
                        t for t in (tools or [])
                        if isinstance(t, dict)
                        and isinstance(t.get("function"), dict)
                        and t["function"].get("name") == name
                    ),
                    None,
                )
                tool_schema = tool_entry.get("function", {}) if tool_entry else {}
                schema_error = parse_error
                if not schema_error and tool_entry is None:
                    schema_error = f"tool {name or '(không tên)'} không có trong danh sách được phép"
                if not schema_error:
                    schema_error = _validate_tool_arguments(
                        tool_schema.get("parameters", {}), parsed_args,
                    )
                normalized_calls.append((call_id, name, parsed_args, schema_error))
                assistant_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": raw_args if isinstance(raw_args, str) else parsed_args,
                    },
                })

            current_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": assistant_calls,
            })

            should_continue = False
            for call_id, name, args, schema_error in normalized_calls:
                if not name:
                    result_text = "Tool call không có tên hợp lệ."
                    action_kind = Action.ERROR
                    action_response = None
                elif schema_error:
                    result_text = f"Arguments của tool {name} không hợp lệ: {schema_error}."
                    action_kind = Action.ERROR
                    action_response = None
                elif (
                    require_lamp_tool
                    and bool(_lamp_tool_categories(name) & required_lamp_categories)
                    and bool(_lamp_tool_categories(name) & attempted_lamp_categories)
                ):
                    result_text = f"Tool {name} đã được gọi trong lượt này; không gọi lặp lại để tránh thực hiện thao tác hai lần."
                    action_kind = Action.ERROR
                    action_response = None
                elif (
                    require_lamp_tool
                    and not required_lamp_categories.issubset(confirmed_lamp_categories)
                    and not _lamp_tool_matches_request(last_user, name, required_lamp_categories)
                ):
                    result_text = f"Tool {name} không phù hợp với yêu cầu điều khiển đèn hiện tại."
                    action_kind = Action.ERROR
                    action_response = None
                else:
                    if require_lamp_tool:
                        attempted_lamp_categories.update(
                            _lamp_tool_categories(name) & required_lamp_categories
                        )
                    self.log.info(f"Tool call [{call_id}]: {name}({args})")
                    action_resp = await self.tool_handler.execute(self, name, args)
                    result_text = str(action_resp.result or action_resp.response or "")
                    action_kind = action_resp.action
                    action_response = action_resp.response
                    categories = _lamp_tool_categories(name) & required_lamp_categories
                    unconfirmed_categories = categories - confirmed_lamp_categories
                    if (
                        require_lamp_tool
                        and unconfirmed_categories
                        and _is_lamp_control_tool(name)
                        and action_kind == Action.REQLLM
                        and _tool_result_confirms_lamp_action(name, args, result_text)
                    ):
                        confirmed_lamp_categories.update(unconfirmed_categories)
                        self.log.info(f"✅ Device action confirmed by MCP result: {name}")

                _lookup_tools = {
                    "web_search", "list_calendar", "get_weather",
                    "get_forecast", "get_news", "get_exchange_rate",
                }
                _max_tool_chars = 1000 if name in _lookup_tools else 400
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _compact_tool_result(result_text, max_chars=_max_tool_chars),
                })

                if action_kind in (Action.RESPONSE, Action.RECORD):
                    if require_lamp_tool and not required_lamp_categories.issubset(confirmed_lamp_categories):
                        should_continue = True
                        continue
                    final_text = _clean_response(str(action_response or result_text).strip())
                    response_text = _clean_response("".join(token_parts).strip())
                    text_to_emit = response_text if (hold_tokens and response_text) else final_text
                    if text_to_emit:
                        await self._emit_token(text_to_emit, on_token=on_token)
                    return text_to_emit

                if action_kind in (Action.REQLLM, Action.NOTFOUND, Action.ERROR):
                    should_continue = True

            if require_lamp_tool and not required_lamp_categories.issubset(confirmed_lamp_categories) and iteration + 1 < max_iter:
                self.log.warning("⚠️ Tool call chưa xác nhận đủ thao tác đèn — yêu cầu model thử lại")
                current_messages.append({
                    "role": "system",
                    "content": (
                        "Kết quả vừa rồi chưa xác nhận yêu cầu điều khiển đèn. Hãy gọi đúng tool điều khiển đèn "
                        "được liệt kê trong schema hiện tại, kiểm tra tham số theo schema, "
                        "và không khẳng định thành công khi chưa có kết quả thiết bị phù hợp."
                    ),
                })
                continue

            if not should_continue:
                if require_lamp_tool and not required_lamp_categories.issubset(confirmed_lamp_categories):
                    break
                return ""

        if require_lamp_tool and not required_lamp_categories.issubset(confirmed_lamp_categories):
            final_text = "Mình chưa thể xác nhận đã điều khiển được đèn. Bạn thử lại giúp mình nhé."
            await self._emit_token(final_text, on_token=on_token)
            return final_text

        self.log.warning(f"Vượt quá {max_iter} vòng tool calling")
        return "Mình chưa thể hoàn tất yêu cầu vì đã vượt quá số lần gọi công cụ cho phép."

    async def _stream_llm_tts(self, messages: list, tools=None, skip_intent: bool = False) -> str:
        """Pipeline LLM -> TTS song song kèm Audio Reorderer."""
        full_response = ""
        sentence_count = 0
        token_count = 0
        buffer = ""

        tts_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        stop_marker = object()
        num_workers = max(1, config.tts_workers)
        llm_timeout = max(10.0, float(config.llm_request_timeout))

        reorderer = AudioReorderer(self._send_callback, self.log)
        reorderer.start()
        await self._send_callback({"type": "tts_start"})

        async def tts_consumer(worker_id: int):
            while True:
                item = await tts_queue.get()
                if item is stop_marker:
                    break
                idx, sentence = item
                try:
                    t0 = time.perf_counter()
                    audio = await asyncio.wait_for(
                        self.tts.synthesize(sentence),
                        timeout=max(10.0, float(config.tts_request_timeout)),
                    )
                    elapsed = (time.perf_counter() - t0) * 1000
                    if audio:
                        await reorderer.push(idx, sentence, audio)
                        self.log.info(f"W{worker_id} cau #{idx} ({len(audio)}b, TTS={elapsed:.0f}ms)")
                    else:
                        await reorderer.skip(idx)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await reorderer.skip(idx)

        async def on_token(tok: str):
            nonlocal sentence_count, buffer, token_count
            token_count += 1
            buffer += tok
            sents, buffer = extract_sentences(buffer)
            for s in sents:
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    tts_queue.put_nowait((sentence_count, s))
                except asyncio.QueueFull:
                    await reorderer.skip(sentence_count)

        cancelled = False
        consumers = [asyncio.create_task(tts_consumer(i + 1)) for i in range(num_workers)]

        try:
            full_response = await asyncio.wait_for(
                self.chat_with_tools(messages, tools or [], on_token=on_token, skip_intent=skip_intent),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            self.log.error(f"⏰ LLM timeout sau {llm_timeout}s")
            await self._send_error("AI đang quá chậm hoặc không phản hồi.")
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as e:
            self.log.exception(f"❌ LLM stream lỗi: {e}")
        finally:
            remainder = buffer.strip()
            if remainder and (len(remainder) >= config.min_sentence_len or sentence_count == 0):
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    tts_queue.put_nowait((sentence_count, remainder))
                except asyncio.QueueFull:
                    await reorderer.skip(sentence_count)

            if cancelled:
                for c in consumers:
                    if not c.done():
                        c.cancel()
                await asyncio.gather(*consumers, return_exceptions=True)
                await reorderer.close(wait=False)
            else:
                for _ in range(num_workers):
                    try:
                        await asyncio.wait_for(tts_queue.put(stop_marker), timeout=5.0)
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*consumers, return_exceptions=True),
                        timeout=max(10.0, float(config.tts_request_timeout) + 5.0),
                    )
                except asyncio.TimeoutError:
                    for c in consumers:
                        if not c.done():
                            c.cancel()
                    await asyncio.gather(*consumers, return_exceptions=True)
                await reorderer.close(wait=True)

            try:
                await self._send_callback({"type": "tts_stop"})
            except Exception as e:
                self.log.debug(f"Gửi tts_stop lỗi: {e}")

            await self.flush_pending_music()

        self.log.info(f"✅ Xong: {token_count} tokens, {sentence_count} câu")
        await set_ai_visual_state("idle", self.log)
        return full_response

    async def _send_callback(self, payload: dict):
        if self._closed:
            return
        try:
            ptype = payload.get("type")
            if ptype == "token":
                content = payload.get("content")
                if content and isinstance(content, str):
                    filtered = _filter_chinese(content)
                    if filtered != content:
                        payload = dict(payload, content=filtered)

            if ptype == "audio":
                self._captured["bot_mp3_parts"].append(payload["data"])
                meta = {
                    "type": "audio_meta",
                    "index": payload.get("index", 0),
                    "size": len(payload["data"]),
                    "sentence": payload.get("sentence", ""),
                    **({"reminder_id": payload["reminder_id"]} if payload.get("reminder_id") else {}),
                }
                await asyncio.wait_for(self.ws.send_json(meta), timeout=10.0)
                await asyncio.wait_for(self.ws.send_bytes(payload["data"]), timeout=10.0)
            elif ptype == "music":
                audio = payload.get("data") or b""
                if not audio:
                    return
                try:
                    audio = await ogg_to_browser_mp3(audio)
                except MusicError as exc:
                    self.log.error(f"🎵 Không chuyển được nhạc cho trình duyệt: {exc}")
                    await asyncio.wait_for(self.ws.send_json({
                        "type": "music_status",
                        "stage": "error",
                        "label": payload.get("label", ""),
                    }), timeout=10.0)
                    return
                await asyncio.wait_for(self.ws.send_json({
                    "type": "music_meta",
                    "size": len(audio),
                    "label": payload.get("label", ""),
                    "mime": "audio/mpeg",
                }), timeout=10.0)
                await asyncio.wait_for(self.ws.send_bytes(audio), timeout=30.0)
            elif ptype == "user_wav":
                pass
            else:
                await asyncio.wait_for(self.ws.send_json(payload), timeout=10.0)
        except asyncio.TimeoutError:
            self._closed = True
            self.log.error("WebSocket send timeout sau 10s")
        except Exception as e:
            self.log.warning(f"⚠️ send_callback: {e}")

    async def _quick_response(self, user_text: str, response: str) -> str:
        """Trả lời text ngay, còn TTS chạy nền và được quản lý theo turn."""
        self.log.info(f"🤖 Quick response: {response!r}")

        self.dialogue.append_user(user_text)
        self.dialogue.append_assistant(response)
        self._captured["bot_mp3_parts"] = []

        try:
            await self._send_callback({"type": "token", "content": response})
        except Exception as e:
            self.log.warning(f"Quick token lỗi: {e}")

        max_quick_chars = max(120, int(getattr(config, "quick_tts_max_chars", 220)))
        tts_text = response[:max_quick_chars].rsplit(" ", 1)[0] if len(response) > max_quick_chars else response
        if len(response) > max_quick_chars and not tts_text.rstrip().endswith((".", "!", "?")):
            tts_text = tts_text.rstrip(",;:") + "."

        if self._quick_tts_task and not self._quick_tts_task.done():
            self._quick_tts_task.cancel()
            await asyncio.gather(self._quick_tts_task, return_exceptions=True)

        async def synthesize_quick_audio():
            cache = get_cache()
            audio = cache.get(tts_text, config.tts_voice)
            if audio is None:
                audio = await asyncio.wait_for(self.tts.synthesize(tts_text), timeout=15.0)
                if audio:
                    cache.put(tts_text, audio, config.tts_voice)
            if audio:
                CHUNK_SIZE = 400_000
                total = (len(audio) + CHUNK_SIZE - 1) // CHUNK_SIZE
                if total > 1:
                    self.log.warning(f"⚠️ Audio {len(audio)}b → {total} chunks")
                for i, start in enumerate(range(0, len(audio), CHUNK_SIZE), 1):
                    chunk = audio[start:start + CHUNK_SIZE]
                    await self._send_callback({
                        "type": "audio",
                        "index": i,
                        "total": total,
                        "sentence": tts_text if i == 1 else "",
                        "data": chunk,
                    })
                await self._send_callback({"type": "tts_stop"})
                self.log.info(f"🔊 Quick TTS: {len(audio)}b")
            else:
                self.log.warning("Quick TTS trả rỗng")

        self._quick_tts_task = asyncio.create_task(synthesize_quick_audio())
        self._background_tasks.add(self._quick_tts_task)
        self._quick_tts_task.add_done_callback(self._background_tasks.discard)
        return response

    async def wait_for_quick_audio(self):
        task = self._quick_tts_task
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.log.warning(f"Quick TTS lỗi: {e}")

    async def flush_pending_music(self):
        pending_music = self._pending_music
        self._pending_music = None
        if not pending_music or not pending_music.get("audio"):
            return
        audio = pending_music["audio"]
        self.log.info(f"🎵 Gửi music xuống client: {pending_music.get('label', '')!r} {len(audio)}b")
        await self._send_callback({
            "type": "music",
            "label": pending_music.get("label", ""),
            "mime": "audio/ogg",
            "data": audio,
        })

    async def _send_error(self, message: str):
        await self._send_callback({"type": "error", "text": message})

    async def send_end(self):
        if self._end_sent:
            return
        self._end_sent = True

        await self._send_callback({"type": "end"})
        if self._close_after_end and hasattr(self.ws, "send_audio"):
            self._close_after_end = False
            # Closing the ESP32 audio socket returns firmware to wake-word idle.
            await self.ws.close()
            return
        await asyncio.sleep(0.5)
        if self._close_after_end:
            self._close_after_end = False
            await self._send_callback({"type": "listen", "state": "stop"})
            return

        await self._send_callback({
            "type": "listen",
            "state": "start",
            "mode": "auto",
        })

    def get_captured(self, key: str):
        if key == "bot_mp3":
            parts = self._captured.get("bot_mp3_parts") or []
            return b"".join(parts) if parts else None
        return self._captured.get(key)

    def load_history(self, history: list):
        """Load history từ DB vào dialogue."""
        for h in history:
            self.dialogue.put(Message(role=h["role"], content=h["content"]))

    async def ack_reminder(self, reminder_id: str) -> None:
        try:
            from app.core.reminder_engine import get_engine
            await get_engine().ack(reminder_id)
        except Exception as e:
            self.log.warning(f"ack_reminder failed: {e}")
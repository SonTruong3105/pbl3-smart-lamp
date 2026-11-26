"""Scene presets + schedule tool cho den thong minh."""
import re
from loguru import logger

SCENES = {
    "doc sach":  {"brightness": 90,  "color_temp": 65, "r": 255, "g": 250, "b": 240, "label": "đọc sách"},
    "ngu":       {"brightness": 5,   "color_temp": 5,  "r": 255, "g": 180, "b": 100, "label": "ngủ"},
    "lam viec":  {"brightness": 100, "color_temp": 75, "r": 240, "g": 245, "b": 255, "label": "làm việc"},
    "thu gian":  {"brightness": 50,  "color_temp": 30, "r": 255, "g": 200, "b": 150, "label": "thư giãn"},
    "tiec":      {"brightness": 100, "color_temp": 50, "r": 255, "g": 100, "b": 200, "label": "tiệc"},
    "phim":      {"brightness": 20,  "color_temp": 15, "r": 180, "g": 100, "b": 80,  "label": "phim"},
    "bao thuc":  {"brightness": 100, "color_temp": 80, "r": 255, "g": 255, "b": 255, "label": "báo thức"},
    "yen tinh":  {"brightness": 15,  "color_temp": 25, "r": 200, "g": 180, "b": 150, "label": "yên tĩnh"},
}

SCENE_ALIASES = {
    "đọc truyện": "doc sach", "đọc": "doc sach", "học": "lam viec",
    "làm bài": "lam viec", "coding": "lam viec", "code": "lam viec",
    "xem phim": "phim", "netflix": "phim", "cinema": "phim",
    "party": "tiec", "quẩy": "tiec",
    "sleep": "ngu", "đi ngủ": "ngu", "ngủ trưa": "ngu",
    "relax": "thu gian", "thư thái": "thu gian",
    "wake": "bao thuc", "alarm": "bao thuc",
    "im": "yen tinh", "quiet": "yen tinh", "silent": "yen tinh",
}


def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _match_scene(text: str) -> str | None:
    t = _norm(text)
    if not t:
        return None
    for key in SCENES:
        if key in t.replace("đ", "d") or key in t:
            return key
    for alias, target in SCENE_ALIASES.items():
        if alias in t:
            return target
    return None


async def _tool_set_scene(scene: str = "", device_id: str | None = None) -> str:
    from app.core.providers.tools.builtin import _send_mcp_command
    if device_id is None:
        from app.core.providers.tools.context import get_connection
        conn = get_connection()
        device_id = getattr(conn, "device_id", None)
    matched = _match_scene(scene)
    if not matched:
        opts = ", ".join(v["label"] for v in SCENES.values())
        return f"Mình có các chế độ: {opts}. Bạn muốn chế độ nào?"
    p = SCENES[matched]
    try:
        brightness_result = await _send_mcp_command(
            "Lamp.SetBrightness", {"value": p["brightness"]}, timeout=2.0, device_id=device_id
        )
        color_result = await _send_mcp_command(
            "Lamp.SetColorTemp", {"value": p["color_temp"]}, timeout=2.0, device_id=device_id
        )
        if brightness_result.get("ok") and color_result.get("ok"):
            return f"Đã chuyển sang chế độ {p['label']}."
        return f"Chưa chuyển được chế độ {p['label']}: thiết bị không xác nhận đủ các thay đổi."
    except Exception as e:
        logger.warning(f"set_scene loi: {e}")
        return f"Không đổi được chế độ: {e}"


def _parse_time_str(time_str: str):
    s = (time_str or "").lower().strip()
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*(?:[:hg]|giờ|gio)\s*(\d{1,2})?", s)
    if not m:
        m = re.search(r"(\d{1,2})", s)
        if not m:
            return None
        hour = int(m.group(1))
        minute = 0
    else:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
    if any(w in s for w in ("chieu", "toi", "dem", "chiều", "tối", "đêm")) and hour < 12:
        hour += 12
    elif any(w in s for w in ("sang", "sáng")) and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


async def _tool_set_schedule(time_str: str = "", action: str = "turn_on", scene: str = "") -> str:
    from app.core.providers.tools.context import get_connection
    conn = get_connection()
    device_id = getattr(conn, "device_id", None)
    parsed = _parse_time_str(time_str)
    if not parsed:
        return f"Mình chưa hiểu giờ '{time_str}'. Bạn nói '7 giờ sáng' được không?"
    hour, minute = parsed

    try:
        from app.core.scheduler import add_lamp_schedule
    except ImportError:
        return "Scheduler chưa cài. Chạy: pip install apscheduler"

    try:
        if action == "set_scene":
            matched = _match_scene(scene) or scene
            await add_lamp_schedule(hour, minute, "set_scene", device_id=device_id, scene=matched)
            label = SCENES.get(matched, {}).get("label", matched)
            return f"Đã hẹn {hour:02d}:{minute:02d} chuyển sang chế độ {label}."
        elif action == "turn_on":
            await add_lamp_schedule(hour, minute, "turn_on", device_id=device_id)
            return f"Đã hẹn {hour:02d}:{minute:02d} bật đèn."
        elif action == "turn_off":
            await add_lamp_schedule(hour, minute, "turn_off", device_id=device_id)
            return f"Đã hẹn {hour:02d}:{minute:02d} tắt đèn."
        return f"Mình chưa rõ hành động '{action}'."
    except Exception as e:
        logger.warning(f"set_schedule loi: {e}")
        return f"Không đặt được lịch: {e}"


# ═══ COLOR TEMP MAPPING ═══
COLOR_TEMP_MAP = {
    "vàng ấm": 0, "ấm": 0, "màu vàng": 0, "ánh sáng ấm": 0,
    "ấm nhẹ": 25, "hơi ấm": 25,
    "trung tính": 50, "tự nhiên": 50, "neutral": 50, "bình thường": 50,
    "lạnh nhẹ": 75, "hơi lạnh": 75,
    "trắng": 100, "trắng sáng": 100, "lạnh": 100, "cool": 100, "ánh sáng trắng": 100,
}


def kelvin_to_value(kelvin: int) -> int:
    """Quy đổi Kelvin (3000-6000) sang value (0-100)."""
    if not isinstance(kelvin, (int, float)):
        return 50
    kelvin = max(3000, min(6000, int(kelvin)))
    return int((kelvin - 3000) / 30)


def value_to_kelvin(value: int) -> int:
    """Quy đổi value (0-100) sang Kelvin (3000-6000)."""
    if not isinstance(value, (int, float)):
        return 4500
    value = max(0, min(100, int(value)))
    return 3000 + value * 30


def parse_color_temp_from_text(text: str) -> int | None:
    """Parse màu từ text tự nhiên sang giá trị 0-100."""
    if not text:
        return None
    t = text.lower().strip()
    
    kelvin_match = re.search(r"(\d{4})\s*(?:k|kelvin)", t)
    if kelvin_match:
        kelvin = int(kelvin_match.group(1))
        if 3000 <= kelvin <= 6000:
            return kelvin_to_value(kelvin)
    
    if t.isdigit():
        val = int(t)
        if 0 <= val <= 100:
            return val
    
    for key, value in COLOR_TEMP_MAP.items():
        if key in t:
            return value
    
    return None

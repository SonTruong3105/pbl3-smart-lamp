"""Bộ lọc Intent & dựng OpenAI Tool Schema theo triết lý Device-Centric MCP."""
from __future__ import annotations

import re
from typing import Optional

from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
from app.core.providers.tools.registry import select_server_tool_names
from app.core.providers.tools.unified import FunctionRegistry

PURE_CHAT_HINTS = re.compile(
    r"\b(xin\s+chào|chào\s+bạn|chào\s+đèn|chào\s+em|hế\s+lô|hê\s+lô|"
    r"hello|hi\b|hey|"
    r"cảm\s+ơn|thanks|thank\s+you|tạm\s+biệt|bye|goodbye|"
    r"vui|buồn|mệt|khỏe|hạnh\s+phúc|lo\s+lắng|chán|"
    r"bạn\s+là\s+ai|tên\s+bạn|bạn\s+tên|"
    r"kể\s+chuyện|nói\s+về|tâm\s+sự|"
    r"yêu|thương|ghét|giận|nhớ)\b",
    re.IGNORECASE,
)

TOOL_SIGNAL_RE = re.compile(
    r"\b(đèn|đền|bóng\s+đèn|màu|mau|kelvin|trung\s+tính|trúng\s+tính|"
    r"lịch|lịch\s+trình|lịch\s+hẹn|sự\s+kiện|"
    r"thời\s+tiết|nhiệt\s+độ|độ\s+ẩm|ánh\s+sáng|không\s+khí|"
    r"tin(?:\s+(?:tức|thể\s+thao|bóng\s+đá|công\s+nghệ|kinh\s+tế|thế\s+giới|trong\s+nước|nóng|nhanh))?|"
    r"điểm\s+tin|bản\s+tin|thời\s+sự|kết\s+quả\s+bóng\s+đá|tỷ\s+số|lịch\s+thi\s+đấu|"
    r"giá\s+vàng|giá|tỷ\s+giá|bitcoin|tra\s+cứu|tìm\s+kiếm|"
    r"bật|bập|thắp|tắt|mở|đóng|đặt|thêm|xóa|sửa|tăng|giảm|chỉnh|đổi|chuyển|"
    r"cảm\s+biến|hiện\s+diện|pm2\.?5|bụi\s+mịn|"
    r"mấy\s+giờ|thứ\s+mấy|ngày\s+mấy|hôm\s+nay|ngày\s+mai|"
    r"nhạc|bài\s+hát|phát\s+nhạc|loa|âm\s+lượng)\b",
    re.IGNORECASE,
)

MUSIC_REQUEST_RE = re.compile(
    r"(?i)\b(?:phát|hạt|nghe|bật|mở)\s+(?:bài(?:\s+hát)?|nhạc|playlist|youtube)\b|"
    r"\b(?:phát\s+nhạc|mở\s+nhạc|nghe\s+nhạc)\b",
    re.IGNORECASE,
)

_WEB_SEARCH_RE = re.compile(
    r"\b(tìm\s+kiếm|tra\s+cứu|điểm\s+tin|bản\s+tin|thời\s+sự|"
    r"giá\s+vàng|giá\s+đô|giá\s+xăng|chứng\s+khoán|tỷ\s+giá|bitcoin|mới\s+nhất|"
    r"kết\s+quả\s+bóng\s+đá|tỷ\s+số|lịch\s+thi\s+đấu|world\s+cup|euro|v-league|ngoại\s+hạng\s+anh|"
    r"ai\s+là|là\s+gì|ở\s+đâu|khi\s+nào|năm\s+nào|"
    r"tin(?:\s+(?:tức|thể\s+thao|bóng\s+đá|công\s+nghệ|kinh\s+tế|thế\s+giới|trong\s+nước|nóng|nhanh))?)\b",
    re.IGNORECASE,
)

_COLOR_PHRASE_RE = re.compile(
    r"\b(?:nhiệt\s+độ\s+màu|màu|mau|kelvin|trung\s+tính|trúng\s+tính|"
    r"vàng\s+ấm|ấm|vàng|trắng\s+lạnh|trắng\s+sáng|lạnh|"
    r"(?:ba|bốn|tư|năm|sáu)\s+(?:nghìn|ngàn)(?:\s+rưỡi)?\s*(?:k|ca|kelvin)?|"
    r"\d{4}\s*(?:k|ca|kelvin))\b",
    re.IGNORECASE,
)

# Không bắt nhầm chữ "sáng" trong cụm "trắng sáng" thành yêu cầu chỉnh độ sáng
_BRIGHTNESS_PHRASE_RE = re.compile(
    r"\b(?:độ\s+sáng|tăng\s+sáng|giảm\s+sáng|sáng\s+hơn|tối\s+hơn|sáng\s+lên|tối\s+xuống|sáng\s+thêm|tối\s+bớt|dim)\b|"
    r"(?<!trắng\s)\b(?:sáng|tối)\b",
    re.IGNORECASE,
)

_DEVICE_ALIASES = (
    (re.compile(r"\b(?:đèn|đền|bóng\s+đèn)\b", re.I), ("lamp", "light")),
    (re.compile(r"\b(?:bật|bập|thắp|mở)\b", re.I), ("turnon", "turn_on", "poweron", "power_on")),
    (re.compile(r"\b(?:tắt|đóng)\b", re.I), ("turnoff", "turn_off", "poweroff", "power_off")),
    (_BRIGHTNESS_PHRASE_RE, ("brightness", "dim", "brightnesstemp", "brightness_temp")),
    (_COLOR_PHRASE_RE, ("color", "colour", "kelvin", "colortemp", "color_temp", "warmcool", "warm_cool", "brightnesstemp", "brightness_temp", "warm", "cool")),
    (re.compile(r"\b(?:chế\s+độ\s+tự\s+động|tự\s+động|auto\s+mode)\b", re.I), ("automode", "auto_mode", "setauto")),
    (re.compile(r"\b(?:quạt|ventilator)\b", re.I), ("fan", "ventilator")),
    (re.compile(r"\b(?:loa|âm\s+lượng|volume)\b", re.I), ("speaker", "audio", "volume")),
    (re.compile(r"\b(?:cửa|khóa|khoá)\b", re.I), ("door", "lock")),
    (re.compile(r"\b(?:độ\s+ẩm|ẩm\s+độ)\b", re.I), ("humidity",)),
    # Chỉ khớp "nhiệt độ" khi KHÔNG đi kèm chữ "màu" ngay sau
    (re.compile(r"\bnhiệt\s+độ(?!\s+màu)\b", re.I), ("temperature", "temp", "sensor", "environment")),
    (re.compile(r"\b(?:bụi\s+mịn|pm2\.?5)\b", re.I), ("pm25", "pm2.5")),
)

_DEVICE_ACTION_RE = re.compile(
    r"\b(?:bật|bập|thắp|tắt|mở|đóng|tăng|giảm|chỉnh|điều\s+chỉnh|đặt|đổi|chuyển|chuyện|"
    r"sáng\s+hơn|tối\s+hơn|sáng\s+lên|tối\s+xuống|sáng\s+thêm|tối\s+bớt)\b",
    re.I,
)
_DEVICE_NEGATION_RE = re.compile(
    r"\b(?:đừng|chớ|không\s+(?:(?:cần|muốn|được|định)\s+)*|khỏi|thôi\s+đừng)\b",
    re.I,
)


def _select_relevant_device_tools(device_tools: list, query: str) -> tuple[list, bool]:
    """Thu gọn MCP schemas theo các nhóm chức năng khớp trong câu (hỗ trợ cả lệnh đơn & lệnh ghép)."""
    if not device_tools or not query:
        return device_tools, False

    generic_device_aliases = {"lamp", "light"}
    active_alias_groups = [
        set(replacements)
        for pattern, replacements in _DEVICE_ALIASES
        if pattern.search(query)
    ]

    # Nếu câu yêu cầu "chế độ tự động", ưu tiên nhóm automode và bỏ nhóm turnon/turnoff chung
    auto_aliases = {"automode", "auto_mode", "setauto"}
    if any(group == auto_aliases for group in active_alias_groups):
        on_off_aliases = {"turnon", "turn_on", "poweron", "power_on", "turnoff", "turn_off", "poweroff", "power_off"}
        active_alias_groups = [g for g in active_alias_groups if not g <= on_off_aliases]

    functional_groups = [group for group in active_alias_groups if not group <= generic_device_aliases]
    if not functional_groups:
        return device_tools, False

    target_aliases = {"lamp", "light", "fan", "ventilator", "speaker", "audio", "door", "lock"}
    target_groups = [group for group in active_alias_groups if group & target_aliases]
    power_groups = (
        {"turnon", "turn_on", "poweron", "power_on"},
        {"turnoff", "turn_off", "poweroff", "power_off"},
    )
    if not target_groups and any(group in power_groups for group in active_alias_groups):
        return device_tools, False
    color_aliases = {"color", "colour", "kelvin", "colortemp", "color_temp", "warmcool", "warm_cool"}
    brightness_aliases = {"brightness", "dim"}
    needs_color = any(group & color_aliases for group in functional_groups)
    needs_brightness = any(group & brightness_aliases for group in functional_groups)
    has_combined_brightness_temp = any(
        isinstance(tool, dict)
        and "setbrightnesstemp" in "".join(re.findall(
            r"[\w]+", str((tool.get("function") or {}).get("name", "")).lower(),
        )).replace("_", "")
        for tool in device_tools
    )
    matched_tools = []
    for tool in device_tools:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = str(function.get("name", ""))
        description = str(function.get("description", ""))
        searchable = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", f"{name} {description}").lower()
        searchable = re.sub(r"[._]+", " ", searchable)
        compact_text = "".join(re.findall(r"[\w]+", searchable))

        if "getstate" in compact_text or "getdevicestatus" in compact_text:
            continue

        tool_name_compact = "".join(re.findall(r"[\w]+", name.lower())).replace("_", "")
        is_brightness_temp_tool = "setbrightnesstemp" in tool_name_compact or "brightnessandtemp" in tool_name_compact
        matches_action = any(
            any(re.sub(r"[^\w]", "", alias.lower()) in compact_text for alias in group)
            and (
                not any(alias in group for alias in ("turnon", "turn_on", "poweron", "power_on"))
                or any(alias in tool_name_compact for alias in ("turnon", "poweron"))
            )
            and (
                not any(alias in group for alias in ("turnoff", "turn_off", "poweroff", "power_off"))
                or any(alias in tool_name_compact for alias in ("turnoff", "poweroff"))
            )
            for group in functional_groups
        )
        if is_brightness_temp_tool:
            matches_action = matches_action and needs_color and needs_brightness
        elif "setwarmcool" in tool_name_compact:
            matches_action = matches_action and needs_color
            if needs_color and needs_brightness and has_combined_brightness_temp:
                matches_action = False
        elif needs_color and needs_brightness and has_combined_brightness_temp:
            matches_action = False
        matches_target = not target_groups or any(
            any(re.sub(r"[^\w]", "", alias.lower()) in compact_text for alias in group)
            for group in target_groups
        )
        if matches_action and matches_target:
            matched_tools.append(tool)

    if matched_tools:
        return matched_tools, True
    return device_tools, False


def is_music_request(text: str) -> bool:
    return bool(text and MUSIC_REQUEST_RE.search(text))


def looks_like_pure_chat(text: str) -> bool:
    if not text:
        return False
    if not PURE_CHAT_HINTS.search(text):
        return False
    if TOOL_SIGNAL_RE.search(text):
        return False
    return True


def build_tool_schema(
    query: str = "",
    domain: str = "chat",
    device_id: Optional[str] = None,
    log=None,
) -> list:
    """Dựng danh sách tool schema: ưu tiên thu gọn MCP tool theo ý định + server tools phù hợp."""
    if domain == "chat" and looks_like_pure_chat(query):
        if log:
            log.info("🔧 Tools (0): pure chat → bỏ qua tool schema")
        return []

    normalized = " ".join((query or "").lower().split())
    allowed = set(select_server_tool_names(normalized))

    has_calendar_intent = bool(re.search(
        r"\b(?:lịch(?:\s+(?:trình|hẹn|học|làm\s+việc))?|sự\s+kiện|cuộc\s+hẹn)\b",
        normalized,
    )) and not re.search(r"\b(?:âm lịch|dương lịch)\b", normalized)

    if has_calendar_intent:
        allowed.add("list_calendar")
    if has_calendar_intent and re.search(r"\b(thêm|tạo|đặt)\b", normalized):
        allowed.add("add_calendar_event")
    if has_calendar_intent and re.search(r"\b(sửa|đổi|cập nhật)\b", normalized):
        allowed.add("update_calendar_event")
    if has_calendar_intent and re.search(r"\b(xóa|hủy|huỷ)\b", normalized):
        allowed.add("delete_calendar_event")

    if re.search(r"\b(thời tiết|dự báo|mưa|nắng\s+không|ngoài\s+trời|nhiệt độ ngoài trời|trời hôm nay)\b", normalized):
        allowed.add("get_forecast" if "dự báo" in normalized else "get_weather")
    if re.search(r"\b(mấy giờ|giờ rồi|thứ mấy|ngày hôm nay|hôm nay là ngày|ngày mai là ngày|âm lịch)\b", normalized):
        allowed.add("get_current_time")
    if _WEB_SEARCH_RE.search(normalized):
        allowed.add("web_search")
    if is_music_request(normalized):
        allowed.add("play_music")

    is_control_action = bool(_DEVICE_ACTION_RE.search(normalized))
    sensor_query = (not is_control_action) and bool(re.search(
        r"\b(độ\s+ẩm|ẩm\s+độ|ánh\s+sáng|lux|bụi\s+mịn|pm2\.?5|"
        r"chất\s+lượng\s+không\s+khí|không\s+khí\s+trong\s+phòng|"
        r"cảm\s+biến|nhiệt\s+độ(?!\s+màu)|hiện\s+diện|có\s+ai|có\s+người)\b",
        normalized,
    ))
    if sensor_query:
        air_quality_query = bool(re.search(r"(chất\s+lượng\s+không\s+khí|không\s+khí)", normalized))
        allowed.add("get_air_quality" if air_quality_query else "get_sensor")

    device_tools = get_device_mcp_manager().get_openai_tools(device_id)
    if sensor_query:
        sensor_device_tools = [
            tool for tool in device_tools
            if tool.get("function", {}).get("name") in {"Sensor.Read", "self.get_environment"}
        ]
        server_preview = FunctionRegistry(allowed).to_openai_schema()
        if any(t.get("function", {}).get("name") in {"get_sensor", "get_air_quality"} for t in server_preview):
            device_tools = []
        elif sensor_device_tools:
            device_tools = sensor_device_tools[:1]

    should_narrow_device_tools = (
        is_control_action
        and not bool(_DEVICE_NEGATION_RE.search(normalized))
    )
    if should_narrow_device_tools:
        device_tools, narrowed = _select_relevant_device_tools(device_tools, normalized)
        if log and narrowed:
            log.info(f"🔧 Rút gọn MCP tools theo yêu cầu: {len(device_tools)} tool")

    device_tool_names = {
        t.get("function", {}).get("name")
        for t in device_tools
        if isinstance(t, dict)
    }

    server_tools = [
        t for t in FunctionRegistry(allowed).to_openai_schema()
        if t.get("function", {}).get("name") not in device_tool_names
    ]

    tools = device_tools + server_tools
    if log:
        log.info(
            f"🔧 Tools ({len(tools)} = {len(device_tools)} device + {len(server_tools)} server): "
            f"{[t['function']['name'] for t in tools]}"
        )
    return tools
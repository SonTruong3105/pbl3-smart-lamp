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
    r"\b(đèn|lịch|lịch\s+trình|lịch\s+hẹn|sự\s+kiện|"
    r"thời\s+tiết|nhiệt\s+độ|độ\s+ẩm|ánh\s+sáng|không\s+khí|"
    r"tin\s+tức|giá\s+vàng|giá|tỷ\s+giá|bitcoin|"
    r"bật|tắt|mở|đóng|đặt|thêm|xóa|sửa|"
    r"cảm\s+biến|hiện\s+diện|pm2\.?5|bụi\s+mịn|"
    r"mấy\s+giờ|thứ\s+mấy|ngày\s+mấy|hôm\s+nay|ngày\s+mai|"
    r"nhạc|bài\s+hát|phát\s+nhạc)\b",
    re.IGNORECASE,
)

MUSIC_REQUEST_RE = re.compile(
    r"(?i)\b(nhạc|bài\s+hát|music|youtube|playlist)\b|"
    r"\b(phát|nghe|bật|mở)\s+(?:bài|nhạc)",
    re.IGNORECASE,
)


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
    """Dựng danh sách tool schema: luôn gồm toàn bộ MCP tool của thiết bị + server tools phù hợp."""
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
    if re.search(r"\b(tìm kiếm|tra cứu|tin tức|thời sự|giá vàng|tỷ giá|bitcoin|mới nhất)\b", normalized):
        allowed.add("web_search")
    if is_music_request(normalized):
        allowed.add("play_music")

    # Route room-sensor requests to the server's normalized wrappers. These
    # wrappers select the device and MCP method consistently, then fall back
    # to DeviceHub data if live MCP readings are unavailable.
    is_control_action = bool(re.search(
        r"\b(bật|tắt|mở|đóng|tăng|giảm|chỉnh|đặt|đổi|chuyển)\b",
        normalized,
    ))
    sensor_query = (not is_control_action) and bool(re.search(
        r"\b(độ\s+ẩm|ẩm\s+độ|ánh\s+sáng|lux|bụi\s+mịn|pm2\.?5|"
        r"chất\s+lượng\s+không\s+khí|không\s+khí\s+trong\s+phòng|"
        r"cảm\s+biến|nhiệt\s+độ\s+phòng|hiện\s+diện|có\s+ai|có\s+người)\b",
        normalized,
    ))
    if sensor_query:
        air_quality_query = bool(re.search(r"(chất\s+lượng\s+không\s+khí|không\s+khí)", normalized))
        allowed.add("get_air_quality" if air_quality_query else "get_sensor")

    # 1. Device MCP tools. For room-sensor questions, hide raw MCP sensor
    # endpoints so the model uses the normalized server wrappers below rather
    # than choosing inconsistently between self.get_environment / Sensor.Read.
    device_tools = get_device_mcp_manager().get_openai_tools(device_id)
    if sensor_query:
        sensor_device_names = {"self.get_environment", "Sensor.Read"}
        device_tools = [
            tool for tool in device_tools
            if tool.get("function", {}).get("name") not in sensor_device_names
        ]
    device_tool_names = {
        t.get("function", {}).get("name")
        for t in device_tools
        if isinstance(t, dict)
    }

    # 2. Server plugins (tránh trùng tên với device tool)
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

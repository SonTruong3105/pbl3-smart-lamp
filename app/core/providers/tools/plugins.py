"""
Plugin wrappers — đăng ký tool hiện có qua @register_function.
Tái sử dụng logic trong impl.py và scenes.py để tránh trùng lặp.
"""
from __future__ import annotations

import re
from typing import Any
from loguru import logger

# CALENDAR
import app.core.providers.tools.calendar  # noqa: F401
from app.core.device_hub import get_device_hub
from app.core.providers.tools.unified.register import (
    Action,
    ActionResponse,
    ToolType,
    register_function,
)


# ═══════════════ WEATHER ═══════════════
@register_function(
    name="get_weather",
    description="Tra thời tiết hiện tại của một thành phố.",
    parameters={
        "city": {"type": "string", "description": "Tên thành phố", "required": True},
    },
)
async def get_weather(city: str) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_weather
    text = await _tool_get_weather(city)
    return ActionResponse(Action.RESPONSE, result=text, response=text)


@register_function(
    name="get_forecast",
    description="Dự báo thời tiết 1-7 ngày cho thành phố.",
    parameters={
        "city": {"type": "string", "description": "Tên thành phố", "required": True},
        "days": {"type": "integer", "description": "Số ngày (1-7)"},
    },
)
async def get_forecast(city: str, days: int = 3) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_forecast
    try:
        days = int(days)
    except (ValueError, TypeError):
        days = 3
    days = max(1, min(7, days))
    text = await _tool_get_forecast(city, days)
    return ActionResponse(Action.RESPONSE, result=text, response=text)


# ═══════════════ TIME / DATE ═══════════════
@register_function(
    name="get_current_time",
    description="Lấy ngày giờ hiện tại.",
    parameters={},
)
async def get_current_time() -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_current_time
    text = await _tool_get_current_time()
    return ActionResponse(Action.RESPONSE, result=text, response=text)


@register_function(
    name="get_weekday",
    description="Tra thứ trong tuần của một ngày. Ví dụ: 'ngày mai', '17/9/2026'.",
    parameters={
        "date": {"type": "string", "description": "Ngày cần tra", "required": True},
    },
)
async def get_weekday(date: str) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_weekday
    text = await _tool_get_weekday(date)
    return ActionResponse(Action.RESPONSE, result=text, response=text)


@register_function(
    name="days_between",
    description="Tính số ngày giữa hai ngày.",
    parameters={
        "date1": {"type": "string", "description": "Ngày bắt đầu", "required": True},
        "date2": {"type": "string", "description": "Ngày kết thúc", "required": True},
    },
)
async def days_between(date1: str, date2: str) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_days_between
    text = await _tool_days_between(date1, date2)
    return ActionResponse(Action.RESPONSE, result=text, response=text)


@register_function(
    name="get_lunar",
    description="Tra ngày âm lịch.",
    parameters={
        "date": {"type": "string", "description": "Ngày dương lịch (mặc định hôm nay)"},
    },
)
async def get_lunar(date: str = "hôm nay") -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_lunar
    text = await _tool_get_lunar(date)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ CALCULATE ═══════════════
@register_function(
    name="calculate",
    description="Tính toán biểu thức số học. Ví dụ: '2+3*4'.",
    parameters={
        "expression": {"type": "string", "description": "Biểu thức", "required": True},
    },
)
async def calculate(expression: str) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_calculate
    text = await _tool_calculate(expression)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ SENSOR ═══════════════
@register_function(
    name="get_sensor",
    description="Đọc cảm biến: nhiệt độ, độ ẩm, bụi mịn PM2.5, ánh sáng, hiện diện.",
    parameters={
        "sensor": {
            "type": "string",
            "description": "temperature, humidity, pm25, light_lux, presence, all",
        },
    },
)
async def get_sensor(sensor: str = "all") -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_sensor
    text = await _tool_get_sensor(sensor)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="get_air_quality",
    description="Đánh giá chất lượng không khí từ cảm biến bụi mịn PM2.5.",
    parameters={},
)
async def get_air_quality() -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_air_quality
    text = await _tool_get_air_quality()
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ LAMP (MCP) ═══════════════
@register_function(
    name="lamp_turn_on",
    description="Bật đèn bàn.",
    parameters={},
    type=ToolType.WAIT,
)
async def lamp_turn_on() -> ActionResponse:
    from app.core.providers.tools.impl import _tool_lamp_turn_on
    text = await _tool_lamp_turn_on()
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="lamp_turn_off",
    description="Tắt đèn bàn.",
    parameters={},
    type=ToolType.WAIT,
)
async def lamp_turn_off() -> ActionResponse:
    from app.core.providers.tools.impl import _tool_lamp_turn_off
    text = await _tool_lamp_turn_off()
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="lamp_set_brightness",
    description="Đặt độ sáng đèn (0-100).",
    parameters={
        "brightness": {"type": "integer", "description": "0-100", "required": True},
    },
    type=ToolType.WAIT,
)
async def lamp_set_brightness(brightness: int) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_lamp_set_brightness
    text = await _tool_lamp_set_brightness(brightness)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="lamp_set_color_temp",
    description="Đặt nhiệt độ màu đèn (0-100). 0=Ấm, 100=Lạnh.",
    parameters={
        "color_temp": {"type": "integer", "description": "0-100", "required": True},
    },
    type=ToolType.WAIT,
)
async def lamp_set_color_temp(color_temp: int) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_lamp_set_color_temp
    text = await _tool_lamp_set_color_temp(color_temp)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ SCENE / SCHEDULE ═══════════════
@register_function(
    name="set_scene",
    description="Đổi chế độ đèn: đọc sách, ngủ, làm việc, thư giãn, tiệc, phim, báo thức, yên tĩnh.",
    parameters={
        "scene": {"type": "string", "description": "Tên chế độ", "required": True},
    },
    type=ToolType.WAIT,
)
async def set_scene(scene: str) -> ActionResponse:
    from app.core.providers.tools.scenes import _tool_set_scene
    text = await _tool_set_scene(scene)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="set_schedule",
    description="Hẹn giờ bật/tắt đèn hoặc chuyển scene.",
    parameters={
        "time_str": {"type": "string", "description": "Giờ, ví dụ '7 giờ sáng'", "required": True},
        "action": {"type": "string", "description": "turn_on, turn_off, set_scene", "required": True},
        "scene": {"type": "string", "description": "Tên scene nếu action=set_scene"},
    },
    type=ToolType.WAIT,
)
async def set_schedule(
    time_str: str, action: str = "turn_on", scene: str = ""
) -> ActionResponse:
    from app.core.providers.tools.scenes import _tool_set_schedule
    text = await _tool_set_schedule(time_str, action, scene)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ NEWS / FINANCE / SEARCH ═══════════════
@register_function(
    name="web_search",
    description="Tìm kiếm thông tin trên web: giá vàng, chứng khoán, tỷ số, sự kiện mới.",
    parameters={
        "query": {"type": "string", "description": "Câu truy vấn", "required": True},
    },
)
async def web_search(query: str) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_web_search
    text = await _tool_web_search(query)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="get_news",
    description="Lấy tin tức mới nhất từ báo Việt Nam.",
    parameters={
        "category": {"type": "string", "description": "vnexpress, tuoitre, thanhnien, dantri"},
        "topic": {"type": "string", "description": "bong-da, the-thao, kinh-doanh, cong-nghe, giai-tri, the-gioi, phap-luat, suc-khoe, giao-duc"},
        "limit": {"type": "integer", "description": "Số tin (1-10)"},
    },
)
async def get_news(
    category: str = "vnexpress", topic: str = "", limit: int = 5
) -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_news
    text = await _tool_get_news(query="", category=category, limit=limit, topic=topic)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="get_exchange_rate",
    description="Tra tỷ giá ngoại tệ so với VND.",
    parameters={
        "currency": {"type": "string", "description": "Mã ngoại tệ", "required": True},
        "target": {"type": "string", "description": "Mặc định VND"},
    },
)
async def get_exchange_rate(currency: str, target: str = "VND") -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_exchange_rate
    text = await _tool_get_exchange_rate(currency, target)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ DIRECT ANSWER (bắt buộc cho schema cũ) ═══════════════
@register_function(
    name="direct_answer",
    description=(
        "Khi yêu cầu của user KHÔNG khớp với bất kỳ tool nào ở trên, "
        "dùng tool này để trả lời trực tiếp. KHÔNG gọi tool thật nếu không chắc."
    ),
    parameters={
        "response": {
            "type": "string",
            "description": "Nội dung trả lời đầy đủ cho user",
            "required": True,
        },
    },
)
async def direct_answer(response: str) -> ActionResponse:
    """
    Trả lời trực tiếp, bỏ qua LLM lần 2.
    Action.RESPONSE khiến chat_with_tools() gửi response và return ngay.
    """
    return ActionResponse(Action.RESPONSE, response=response, result=response)


# ═══════════════════════════════════════════════════════════════
#  MACRO TOOLS — MCP-first (đồng bộ với firmware ESP32)
# ═══════════════════════════════════════════════════════════════

@register_function(
    name="get_environment",
    description="Đọc cảm biến môi trường phòng (nhiệt độ, độ ẩm, bụi mịn PM2.5, ánh sáng, hiện diện).",
    parameters={
        "field": {
            "type": "string",
            "enum": ["temperature", "humidity", "pm25", "light", "presence", "all"],
        },
    },
)
async def get_environment(field: str = "all") -> ActionResponse:
    """MCP-first: đọc trực tiếp từ ESP32, fallback về cache DeviceHub."""
    field = (field or "all").lower().strip()
    from app.core.providers.tools.context import get_connection
    conn = get_connection()
    device_id = getattr(conn, "device_id", None)

    # ─── 1. Thử MCP (dữ liệu thời gian thực) ───
    try:
        from app.core.providers.tools.impl import _send_mcp_command

        result = await _send_mcp_command(
            "self.get_environment", {"field": field}, timeout=3.0,
            device_id=device_id,
        )
        text = str(result.get("reply") or "")
        if result.get("ok") and text:
            return ActionResponse(Action.RESPONSE, result=text, response=text)
    except Exception as e:
        logger.debug(f"[MCP] get_environment fallback: {e}")

    # ─── 2. Fallback: cache DeviceHub ───
    hub = get_device_hub()
    if not hub.is_sensor_fresh(max_age_sec=300, device_id=device_id):
        text = "Chưa có dữ liệu cảm biến (ESP32 chưa kết nối)."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    data = hub.get_all_sensors(device_id=device_id)

    if field == "temperature":
        v = data.get("temperature")
        text = f"Nhiệt độ phòng: {v}°C" if v is not None else "Chưa có dữ liệu nhiệt độ."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if field == "humidity":
        v = data.get("humidity")
        text = f"Độ ẩm phòng: {v}%" if v is not None else "Chưa có dữ liệu độ ẩm."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if field == "pm25":
        v = data.get("pm25")
        text = f"Bụi mịn PM2.5: {v} µg/m³" if v is not None else "Chưa có dữ liệu bụi mịn PM2.5."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if field == "light":
        v = data.get("light_lux")
        text = f"Ánh sáng: {v} lux" if v is not None else "Chưa có dữ liệu ánh sáng."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if field == "presence":
        v = data.get("presence")
        if v is None:
            text = "Chưa có dữ liệu hiện diện."
        else:
            text = "Có người trong phòng." if v else "Không có người trong phòng."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    # all
    parts = []
    if data.get("temperature") is not None:
        parts.append(f"nhiệt độ {data['temperature']}°C")
    if data.get("humidity") is not None:
        parts.append(f"độ ẩm {data['humidity']}%")
    if data.get("pm25") is not None:
        parts.append(f"bụi mịn PM2.5 {data['pm25']} µg/m³")
    if data.get("light_lux") is not None:
        parts.append(f"ánh sáng {data['light_lux']} lux")
    if data.get("presence") is not None:
        parts.append("có người" if data["presence"] else "không có người")

    if not parts:
        text = "Chưa có dữ liệu cảm biến."
    else:
        text = "Phòng hiện tại: " + ", ".join(parts) + "."
    return ActionResponse(Action.RESPONSE, result=text, response=text)


async def _sync_lamp_state_to_web(device_id: str | None, reply_data: Any) -> None:
    """Đồng bộ trạng thái đèn từ kết quả MCP sang DeviceHub và Web UI."""
    if not device_id:
        return
    try:
        from app.core.device_hub import parse_mcp_result
        parsed = (
            parse_mcp_result({"ok": True, "reply": reply_data})
            if not isinstance(reply_data, dict)
            else reply_data
        )
        if not isinstance(parsed, dict) or not parsed:
            return
        hub = get_device_hub()
        hub.update_lamp(parsed, device_id=device_id)
        await hub.broadcast_sync(device_id, "lamp_update", parsed)
        msg = {
            "type": "lamp_sync",
            "esp32_device_id": device_id,
            "data": parsed,
            **parsed,
        }
        for _web_id, chat_ws in hub.get_chats_by_device(device_id):
            try:
                await chat_ws.send_json(msg)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[MCP] sync lamp to web error: {e}")


def _parse_color_temp_kelvin(raw_val: Any) -> int | None:
    """Chuyển đổi input color_temp (Kelvin, 0-100%, hoặc mô tả tiếng Việt) sang 3000/4500/6000K."""
    if raw_val is None:
        return None
    s = str(raw_val).strip().lower()
    if any(k in s for k in ("ấm", "vàng", "warm")):
        return 3000
    if any(k in s for k in ("trung tính", "tự nhiên", "neutral")):
        return 4500
    if any(k in s for k in ("trắng", "lạnh", "cool", "white")):
        return 6000
    try:
        num = int(float(re.sub(r"[^\d.]", "", s)))
    except (ValueError, TypeError):
        return None
    if 0 <= num <= 100:
        num = 3000 + int(round(num * 30))
    num = max(3000, min(6000, num))
    return min({3000, 4500, 6000}, key=lambda k: abs(k - num))


@register_function(
    name="control_light",
    description=(
        "Điều khiển đèn: bật, tắt, chỉnh độ sáng (0-100%), "
        "nhiệt độ màu (3000K/4500K/6000K hoặc ấm/trung tính/trắng sáng), hoặc chọn chế độ."
    ),
    parameters={
        "action": {"type": "string", "enum": ["on", "off", "set"]},
        "brightness": {"type": "integer"},
        "color_temp": {"type": "string"},
        "scene": {"type": "string"},
    },
)
async def control_light(
    action: str,
    brightness: int = None,
    color_temp: Any = None,
    scene: str = None,
) -> ActionResponse:
    """Router thống nhất cho mọi lệnh điều khiển đèn."""
    from app.core.providers.tools.impl import _send_mcp_command

    action = (action or "on").lower().strip()
    from app.core.providers.tools.context import get_connection
    conn = get_connection()
    device_id = getattr(conn, "device_id", None)

    if action == "on":
        r = await _send_mcp_command("Lamp.TurnOn", device_id=device_id)
        if r.get("ok"):
            await _sync_lamp_state_to_web(device_id, r.get("reply"))
        text = "Đã bật đèn." if r.get("ok") else "Không bật được đèn (chưa kết nối)."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if action == "off":
        r = await _send_mcp_command("Lamp.TurnOff", device_id=device_id)
        if r.get("ok"):
            await _sync_lamp_state_to_web(device_id, r.get("reply"))
        text = "Đã tắt đèn." if r.get("ok") else "Không tắt được đèn (chưa kết nối)."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    if action != "set":
        return ActionResponse(Action.ERROR, result=f"Hành động '{action}' không hợp lệ.")

    # action == "set"
    msgs = []
    failed = []

    if scene:
        try:
            from app.core.providers.tools.scenes import _tool_set_scene
            msg = await _tool_set_scene(scene, device_id=device_id)
            msgs.append(msg)
            if msg.startswith(("Không ", "Chưa ", "Lỗi")):
                failed.append(msg)
            else:
                st = await _send_mcp_command("Lamp.GetState", device_id=device_id)
                if st.get("ok"):
                    await _sync_lamp_state_to_web(device_id, st.get("reply"))
        except Exception as e:
            error = f"Lỗi scene: {e}"
            msgs.append(error)
            failed.append(error)

    if brightness is not None:
        b = max(0, min(100, int(brightness)))
        r = await _send_mcp_command("Lamp.SetBrightness", {"value": b}, device_id=device_id)
        if r.get("ok"):
            await _sync_lamp_state_to_web(device_id, r.get("reply"))
            msgs.append(f"độ sáng {b}%")
        else:
            error = f"không đổi được độ sáng: {r.get('error') or 'thiết bị không phản hồi'}"
            msgs.append(error)
            failed.append(error)

    if color_temp is not None:
        snapped = _parse_color_temp_kelvin(color_temp)
        if snapped is None:
            return ActionResponse(
                Action.ERROR,
                result=f"Nhiệt độ màu '{color_temp}' không hợp lệ.",
            )
        ct_pct = int((snapped - 3000) / 30)  # 3000→0, 4500→50, 6000→100
        r = await _send_mcp_command("Lamp.SetColorTemp", {"value": ct_pct}, device_id=device_id)
        if r.get("ok"):
            await _sync_lamp_state_to_web(device_id, r.get("reply"))
            msgs.append(f"{snapped}K")
        else:
            error = f"không đổi được màu: {r.get('error') or 'thiết bị không phản hồi'}"
            msgs.append(error)
            failed.append(error)

    if not msgs:
        return ActionResponse(Action.ERROR, result="Thiếu tham số: cần brightness, color_temp hoặc scene.")

    if failed:
        text = "Chưa điều chỉnh được đèn: " + "; ".join(failed) + "."
    else:
        text = "Đã điều chỉnh đèn: " + ", ".join(msgs) + "."
    return ActionResponse(Action.RESPONSE, result=text, response=text)


@register_function(
    name="update_display",
    description="Hiển thị text lên màn hình TFT.",
    parameters={
        "text": {"type": "string", "required": True},
    },
)
async def update_display(text: str) -> ActionResponse:
    """Gửi lệnh MCP hiển thị text lên màn hình TFT."""
    from app.core.providers.tools.impl import _send_mcp_command

    if not text:
        return ActionResponse(Action.ERROR, result="Text rỗng.")

    try:
        r = await _send_mcp_command("Screen.SetText", {"text": text[:200]})
        text = "Đã hiển thị lên màn hình." if r.get("ok") else "Không gửi được lên màn hình."
        return ActionResponse(Action.RESPONSE, result=text, response=text)
    except Exception as e:
        return ActionResponse(Action.ERROR, result=f"Lỗi hiển thị: {e}")
"""
Plugin wrappers — đăng ký tool hiện có qua @register_function.
Tái sử dụng logic trong impl.py và scenes.py để tránh trùng lặp.
"""
from __future__ import annotations

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
    return ActionResponse(Action.REQLLM, result=text)


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
    text = await _tool_get_forecast(city, days)
    return ActionResponse(Action.REQLLM, result=text)


# ═══════════════ TIME / DATE ═══════════════
@register_function(
    name="get_current_time",
    description="Lấy ngày giờ hiện tại.",
    parameters={},
)
async def get_current_time() -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_current_time
    text = await _tool_get_current_time()
    return ActionResponse(Action.REQLLM, result=text)


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
    return ActionResponse(Action.REQLLM, result=text)


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
    return ActionResponse(Action.REQLLM, result=text)


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
    description="Đọc cảm biến: nhiệt độ, độ ẩm, không khí, ánh sáng, hiện diện.",
    parameters={
        "sensor": {
            "type": "string",
            "description": "temperature, humidity, air_quality_ppm, light_lux, presence, all",
        },
    },
)
async def get_sensor(sensor: str = "all") -> ActionResponse:
    from app.core.providers.tools.impl import _tool_get_sensor
    text = await _tool_get_sensor(sensor)
    return ActionResponse(Action.REQLLM, result=text)


@register_function(
    name="get_air_quality",
    description="Đánh giá chất lượng không khí từ cảm biến MQ135.",
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

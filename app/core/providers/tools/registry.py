"""Tool registry."""
import json
from loguru import logger


TOOLS_SCHEMA = [
    # ═══ THỜI TIẾT ═══
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Tra thời tiết HIỆN TẠI của một thành phố. "
                "Dùng khi hỏi: thời tiết Hà Nội, trời có mưa không."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Tên thành phố"}
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast",
            "description": "Dự báo thời tiết nhiều ngày tới (tối đa 7 ngày).",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer", "description": "1-7, mặc định 3"},
                },
                "required": ["city"],
            },
        },
    },
    # ═══ TÌM KIẾM ═══
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Tìm kiếm thông tin trên web: giá vàng, chứng khoán, "
                "tỷ số, tin tức, giá sản phẩm, hoặc bất cứ gì cần "
                "thông tin mới từ internet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Câu truy vấn"}
                },
                "required": ["query"],
            },
        },
    },
    # ═══ THỜI GIAN ═══
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Lấy ngày giờ hiện tại. Dùng khi hỏi mấy giờ.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekday",
            "description": (
                "Tra thứ trong tuần. "
                "VD: 'ngày mai là thứ mấy', '17/9 là thứ mấy'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "Hỗ trợ: '17/9/2026', '2026-09-17', "
                            "'hôm nay', 'ngày mai', 'thứ hai tuần sau', '+3', '-2'."
                        ),
                    }
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "days_between",
            "description": "Tính khoảng cách ngày giữa 2 mốc. VD: 'còn mấy ngày đến Tết'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date1": {"type": "string"},
                    "date2": {"type": "string"},
                },
                "required": ["date1", "date2"],
            },
        },
    },
    # ═══ ÂM LỊCH ═══
    {
        "type": "function",
        "function": {
            "name": "get_lunar",
            "description": (
                "Tra ngày ÂM LỊCH VN. Dùng khi hỏi: âm lịch hôm nay, "
                "ngày rằm, mùng 1, Tết, can chi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Ngày dương. VD: 'hôm nay', 'ngày mai', '17/9/2026'.",
                    }
                },
                "required": [],
            },
        },
    },
    # ═══ TIN TỨC ═══
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Lấy tin tức mới nhất từ báo VN. "
                "Dùng khi hỏi: tin tức, thời sự, bản tin."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "vnexpress, tuoitre, thanhnien, dantri",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số tin 1-10, mặc định 5",
                    },
                },
                "required": [],
            },
        },
    },
    # ═══ TỶ GIÁ ═══
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Tra tỷ giá ngoại tệ. VD: USD, EUR, JPY, CNY.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "description": "Mã ngoại tệ"},
                    "target": {"type": "string", "description": "Mặc định VND"},
                },
                "required": ["currency"],
            },
        },
    },
    # ═══ TÍNH TOÁN ═══
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Tính toán. VD: '2+3*4', '(10+5)/3', '2^10'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"}
                },
                "required": ["expression"],
            },
        },
    },
    # ═══ CẢM BIẾN ═══
    {
        "type": "function",
        "function": {
            "name": "get_air_quality",
            "description": (
                "Đọc chất lượng không khí từ MQ135. "
                "Dùng khi hỏi: không khí thế nào, có ô nhiễm không, "
                "khói bụi, khí gas."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ═══ ĐÈN (MCP) ═══
    {
        "type": "function",
        "function": {
            "name": "lamp_turn_on",
            "description": "Bật đèn bàn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_turn_off",
            "description": "Tắt đèn bàn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_set_brightness",
            "description": "Đặt độ sáng đèn (0-100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "brightness": {"type": "integer", "description": "0-100"}
                },
                "required": ["brightness"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lamp_set_color_temp",
            "description": (
                "Đặt nhiệt độ màu đèn (0-100). "
                "0=vàng ấm, 50=trung tính, 100=trắng lạnh."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "color_temp": {"type": "integer", "description": "0-100"}
                },
                "required": ["color_temp"],
            },
        },
    },
    # ═══ CẢM BIẾN (MCP) ═══
    {
        "type": "function",
        "function": {
            "name": "get_sensor",
            "description": (
                "Đọc cảm biến từ ESP32: nhiệt độ, độ ẩm, "
                "không khí, ánh sáng, hiện diện."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor": {
                        "type": "string",
                        "description": (
                            "Tên cảm biến: temperature, humidity, "
                            "air_quality_ppm, light_lux, presence, all"
                        ),
                    }
                },
                "required": [],
            },
        },
    },
]


async def execute_tool(name: str, arguments) -> str:
    from app.core.providers.tools import impl as _impl
    fn = getattr(_impl, f"_tool_{name}", None)
    if not fn:
        logger.warning(f"Tool không tồn tại: {name}")
        return f"Không có tool '{name}'."

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as e:
            logger.error(f"Tool {name}: JSON không hợp lệ: {e}")
            return f"Tham số cho {name} không phải JSON hợp lệ."

    if not isinstance(arguments, dict):
        arguments = {}

    try:
        return await fn(**arguments)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={arguments}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"

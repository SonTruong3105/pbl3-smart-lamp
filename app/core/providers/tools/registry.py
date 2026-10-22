"""Tool registry - Cân bằng giữa tính năng và độ ổn định cho 0.8B."""
import json
from loguru import logger

TOOLS_SCHEMA = [
    # ═══ TRA CỨU NGOÀI (Giữ lại theo yêu cầu) ═══
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Tìm kiếm thông tin trên web: giá vàng, chứng khoán, tỷ số, sự kiện mới.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Câu truy vấn"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Lấy tin tức mới nhất từ báo VN.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "vnexpress, tuoitre, thanhnien, dantri"},
                    "limit": {"type": "integer", "description": "Số tin (1-10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Tra tỷ giá ngoại tệ (USD, EUR, JPY, v.v.) so với VND.",
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
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Tính toán biểu thức. VD: '2+3*4'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"}
                },
                "required": ["expression"],
            },
        },
    },

    # ═══ THỜI TIẾT ═══
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Tra thời tiết hiện tại của thành phố.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Tên thành phố"}
                },
                "required": ["city"],
            },
        },
    },
    # ═══ THỜI GIAN ═══
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Lấy ngày giờ hiện tại.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ═══ CẢM BIẾN ═══
    {
        "type": "function",
        "function": {
            "name": "get_sensor",
            "description": "Đọc cảm biến: nhiệt độ, độ ẩm, không khí, ánh sáng, hiện diện.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor": {
                        "type": "string",
                        "description": "temperature, humidity, air_quality_ppm, light_lux, presence, all",
                    }
                },
                "required": [],
            },
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
            "description": "Đặt nhiệt độ màu đèn (0-100). 0=Ấm, 100=Lạnh.",
            "parameters": {
                "type": "object",
                "properties": {
                    "color_temp": {"type": "integer", "description": "0-100"}
                },
                "required": ["color_temp"],
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
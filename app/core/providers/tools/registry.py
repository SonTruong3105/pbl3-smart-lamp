"""Tool registry - Cân bằng giữa tính năng và độ ổn định cho 0.8B."""
import json
import re
from loguru import logger

# ⭐ Virtual tool: buộc LLM chọn "trả lời trực tiếp" thay vì gọi bừa tool
DIRECT_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "direct_answer",
        "description": "Khi yêu cầu của user KHÔNG khớp với bất kỳ tool nào ở trên, dùng tool này để trả lời trực tiếp. KHÔNG gọi tool thật nếu không chắc chắn.",
        "parameters": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "Nội dung trả lời đầy đủ cho user",
                }
            },
            "required": ["response"],
        },
    },
}

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
                    "topic": {"type": "string", "description": "bong-da, the-thao, kinh-doanh, cong-nghe, giai-tri, the-gioi, phap-luat, suc-khoe, giao-duc"},
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
            "description": "Đọc cảm biến: nhiệt độ, độ ẩm, bụi mịn PM2.5, ánh sáng, hiện diện.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor": {
                        "type": "string",
                        "description": "temperature, humidity, pm25, light_lux, presence, all",
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
    {
        "type": "function",
        "function": {
            "name": "get_forecast",
            "description": "Dự báo thời tiết 1-7 ngày cho thành phố.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 7},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekday",
            "description": "Tra thứ trong tuần của một ngày. VD: 'ngày mai là thứ mấy', '17/9 là thứ mấy'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "hôm nay, ngày mai, 17/9/2026, +3"}
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "days_between",
            "description": "Tính số ngày giữa hai ngày.",
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
    {
        "type": "function",
        "function": {
            "name": "get_lunar",
            "description": "Tra ngày âm lịch.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "default": "hôm nay"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_air_quality",
            "description": "Đánh giá chất lượng không khí từ cảm biến bụi mịn PM2.5.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_scene",
            "description": "Đổi chế độ đèn: đọc sách, ngủ, làm việc, thư giãn, tiệc, phim, báo thức, yên tĩnh.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {"type": "string", "description": "Tên chế độ"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_schedule",
            "description": "Hẹn giờ bật/tắt đèn hoặc chuyển scene. VD: '7 giờ sáng bật đèn', '22 giờ chuyển chế độ ngủ'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_str": {"type": "string", "description": "Giờ: '7 giờ sáng', '22:30', '19 giờ tối'"},
                    "action": {"type": "string", "description": "turn_on, turn_off, set_scene"},
                    "scene": {"type": "string", "description": "Tên scene nếu action=set_scene"},
                },
                "required": ["time_str", "action"],
            },
        },
    },
    DIRECT_ANSWER_TOOL,  # ⭐ Thêm direct_answer như một lựa chọn thay thế
]



# ═══════════════════════════════════════════════════════════════
# Dynamic tool selection — chỉ gửi tool liên quan cho model 2B
# ═══════════════════════════════════════════════════════════════

_TOOL_GROUPS = {
    "device": {"get_sensor", "get_air_quality", "lamp_turn_on", "lamp_turn_off", "set_scene", "set_schedule",
               "lamp_set_brightness", "lamp_set_color_temp"},
    "weather": {"get_weather", "get_forecast"},
    "time": {"get_current_time", "get_weekday", "days_between", "get_lunar"},
    "news": {"get_news"},
    "finance": {"get_exchange_rate", "get_gold_price"},
    "utility": {"calculate"},
    "knowledge": {"web_search"},
}

_QUERY_GROUP_PATTERNS = {
    "utility": re.compile(
        r"(?:\b(tính|tính\s+toán|phép\s+tính|cộng|trừ|nhân|chia|mũ|phẩy)\b"
        r"|\d\s*[+*x^]\s*\d)", re.IGNORECASE),
    "device": re.compile(
        r"\b(đèn|cảm\s+biến|nhiệt\s+độ\s+phòng|độ\s+ẩm|bụi\s+mịn|"
        r"pm2?\.?5|không\s+khí|ánh\s+sáng|có\s+người|"
        r"bật|tắt|mở|đóng|độ\s+sáng|màu\s+đèn|nhiệt\s+độ\s+màu|chế\s+độ|kịch\s+bản|scene|hẹn\s+giờ|báo\s+thức)\b",
        re.IGNORECASE),
    "weather": re.compile(
        r"\b(thời\s+tiết|dự\s+báo|mưa|nhiệt\s+độ\s+ngoài|gió|"
        r"nắng|bão|hôm\s+nay\s+trời|ngày\s+mai\s+trời)\b", re.IGNORECASE),
    "time": re.compile(
        r"\b(mấy\s+giờ|bây\s+giờ|hôm\s+nay\s+là\s+ngày|thứ\s+mấy|"
        r"hôm\s+nay\s+thế\s+nào|"
        r"ngày\s+bao\s+nhiêu|âm\s+lịch|dương\s+lịch|bao\s+nhiêu\s+ngày)\b",
        re.IGNORECASE),
    "news": re.compile(
        r"\b(tin\s+tức|tin\s+mới|thời\s+sự|thể\s+thao|bóng\s+đá|"
        r"mới\s+nhất|tin\s+hôm\s+nay|sự\s+kiện)\b", re.IGNORECASE),
    "finance": re.compile(
        r"\b(tỷ\s+giá|ngoại\s+tệ|đô\s+la|usd|eur|jpy|giá\s+vàng|"
        r"chứng\s+khoán|bitcoin|btc|vàng\s+sjc)\b", re.IGNORECASE),
    "knowledge": re.compile(
        r"\b(tìm|tra\s+cứu|google|tìm\s+kiếm|search|lịch\s+sử|là\s+gì|định\s+nghĩa|khái\s+niệm|"
        r"thông\s+tin\s+về|ai\s+là|ở\s+đâu|hướng\s+dẫn|cách\s+làm|"
        r"tại\s+sao|vì\s+sao|như\s+thế\s+nào)\b", re.IGNORECASE),
}

_GROUP_PRIORITY = ("utility", "device", "weather", "time", "news", "finance", "knowledge")


def tool_names_for_query(query: str) -> set:
    """Chọn 1 nhóm tool nhỏ nhất phù hợp. Fallback web_search cho câu hỏi mở."""
    text = " ".join((query or "").strip().lower().split())
    if not text:
        return set()

    group = next(
        (g for g in _GROUP_PRIORITY if _QUERY_GROUP_PATTERNS[g].search(text)),
        None,
    )

    if group is None:
        if re.search(r"[?？]|\b(tại\s+sao|vì\s+sao|như\s+thế\s+nào|là\s+gì|ai\s+là|ở\s+đâu)\b", text):
            return {"web_search"}
        return set()

    if group == "device":
        if re.search(r"hẹn\s+giờ|báo\s+thức|đặt\s+lịch", text):
            return {"set_schedule"}
        if re.search(r"chế\s+độ|kịch\s+bản|scene", text):
            return {"set_scene"}
        if re.search(r"\b(bật|mở)\b.*\bđèn\b|\bđèn\b.*\b(bật|mở)\b", text):
            return {"lamp_turn_on"}
        if re.search(r"\b(tắt|đóng)\b.*\bđèn\b|\bđèn\b.*\b(tắt|đóng)\b", text):
            return {"lamp_turn_off"}
        if re.search(r"(độ\s+sáng|sáng)\s*\d", text):
            return {"lamp_set_brightness"}
        if re.search(r"(nhiệt\s+độ\s+màu|màu\s+đèn)", text):
            return {"lamp_set_color_temp"}
        if re.search(r"(bụi\s+mịn|pm2?\.?5|không\s+khí)", text):
            return {"get_air_quality", "get_sensor"}
        return {"get_sensor"}
    if group == "weather":
        return {"get_forecast"} if "dự báo" in text else {"get_weather"}
    if group == "time":
        if "thứ" in text:
            return {"get_weekday"}
        if "âm lịch" in text:
            return {"get_lunar"}
        if "bao nhiêu ngày" in text:
            return {"days_between"}
        return {"get_current_time"}
    if group == "finance":
        if "vàng" in text:
            return {"web_search"}  # vang -> web_search
        return {"get_exchange_rate"}
    return set(_TOOL_GROUPS[group])


def tools_for_names(names: set) -> list:
    return [s for s in TOOLS_SCHEMA if s.get("function", {}).get("name") in names]


def tools_for_query(query: str) -> list:
    """Trả về tools phù hợp + luôn kèm direct_answer (theo server gốc)."""
    names = tool_names_for_query(query)
    result = tools_for_names(names)
    # ⭐ Luôn thêm direct_answer để LLM có lựa chọn "trả lời trực tiếp"
    result.append(DIRECT_ANSWER_TOOL)
    return result

async def execute_tool(name: str, arguments) -> str:
    import json as _json
    # ⭐ Xử lý direct_answer
    if name == "direct_answer":
        if isinstance(arguments, str):
            try:
                arguments = _json.loads(arguments)
            except Exception:
                return arguments
        if isinstance(arguments, dict) and "response" in arguments:
            return str(arguments["response"])
        return "Mình chưa rõ ý bạn."
    
    from app.core.providers.tools import impl as _impl
    fn = getattr(_impl, f"_tool_{name}", None)
    if not fn:
        try:
            from app.core.providers.tools import scenes as _scenes
            fn = getattr(_scenes, f"_tool_{name}", None)
        except ImportError:
            pass
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
        import asyncio
        result = await asyncio.wait_for(fn(**arguments), timeout=15.0)  # ⭐ > inner web_search 8s
        try:
            return _impl._compact_text(str(result), max_chars=1500)
        except AttributeError:
            return str(result)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={arguments}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"
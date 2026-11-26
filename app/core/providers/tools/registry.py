"""Tool registry — Hợp nhất server tools và device MCP tools động theo device_id."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
from app.core.providers.tools.unified.register import FunctionItem

# Virtual tool: cho phép LLM trả lời trực tiếp khi không cần gọi tool nào
DIRECT_ANSWER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "direct_answer",
        "description": (
            "Dùng khi yêu cầu KHÔNG cần gọi công cụ nào hoặc khi trả lời hội thoại thông thường."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "Nội dung trả lời ngắn gọn, tự nhiên cho người dùng",
                }
            },
            "required": ["response"],
        },
    },
}

# Chỉ giữ các tool thuần phía server (không hardcode Lamp.* / sensor / scene của thiết bị)
SERVER_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Tìm kiếm thông tin trên web: giá vàng, chứng khoán, tỷ số, sự kiện mới, kiến thức.",
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
            "description": "Tính toán biểu thức toán học. VD: '2+3*4'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"}
                },
                "required": ["expression"],
            },
        },
    },
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
            "name": "get_current_time",
            "description": "Lấy ngày giờ hiện tại.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekday",
            "description": "Tra thứ trong tuần của một ngày.",
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
]

# Alias tương thích ngược cho connection.py / runtime.py
TOOLS_SCHEMA = SERVER_TOOLS_SCHEMA
ALL_TOOL_NAMES = {s["function"]["name"] for s in SERVER_TOOLS_SCHEMA} | {"direct_answer"}

# Chỉ dùng regex để rút gọn nhóm tool ngoại tuyến/tra cứu khi KHÔNG có device MCP tool,
# nhưng LUÔN giữ toàn bộ device MCP tool của device_id hiện tại để LLM tự quyết định.
_SERVER_QUERY_PATTERNS = {
    "calculate": re.compile(r"(?:\b(tính|tính\s+toán|phép\s+tính|cộng|trừ|nhân|chia|mũ)\b|\d\s*[+*x^]\s*\d)", re.IGNORECASE),
    "weather": re.compile(r"\b(thời\s+tiết|dự\s+báo|mưa|gió|nắng|bão|trời\s+(nắng|mưa|lạnh|nóng))\b", re.IGNORECASE),
    "time": re.compile(r"\b(mấy\s+giờ|bây\s+giờ|hôm\s+nay|thứ\s+mấy|âm\s+lịch|bao\s+nhiêu\s+ngày)\b", re.IGNORECASE),
    "news": re.compile(r"\b(tin\s+tức|tin\s+mới|thời\s+sự|thể\s+thao|bóng\s+đá)\b", re.IGNORECASE),
    "finance": re.compile(r"\b(tỷ\s+giá|ngoại\s+tệ|usd|eur|jpy|giá\s+vàng|vàng\s+sjc)\b", re.IGNORECASE),
    "web_search": re.compile(r"\b(tìm|tra\s+cứu|google|tìm\s+kiếm|search|là\s+gì|ai\s+là|ở\s+đâu)\b|[?？]", re.IGNORECASE),
}
QUERY_PATTERNS = _SERVER_QUERY_PATTERNS


def _function_item_to_schema(item: FunctionItem) -> Dict[str, Any]:
    params = item.parameters if isinstance(item.parameters, dict) and item.parameters else {
        "type": "object",
        "properties": {},
    }
    if "type" not in params:
        params = {"type": "object", "properties": params}
    return {
        "type": "function",
        "function": {
            "name": item.name,
            "description": item.description or "",
            "parameters": params,
        },
    }


def get_device_mcp_schemas(device_id: Optional[str]) -> List[Dict[str, Any]]:
    """Lấy danh sách tool schema gốc do đúng thiết bị `device_id` khai báo."""
    if not device_id:
        return []
    mcp_mgr = get_device_mcp_manager()
    items = mcp_mgr.get_device_tools(device_id)
    return [_function_item_to_schema(item) for item in items.values()]


def select_server_tool_names(query: str) -> Set[str]:
    """Chọn các server tool liên quan cho câu hỏi (không chặn device MCP tools)."""
    text = " ".join((query or "").strip().lower().split())
    if not text:
        return set()

    selected: Set[str] = set()
    for tool_name, pattern in _SERVER_QUERY_PATTERNS.items():
        if pattern.search(text):
            if tool_name == "weather":
                selected.add("get_forecast" if "dự báo" in text else "get_weather")
            elif tool_name == "news":
                selected.add("get_news")
            elif tool_name == "time":
                if "thứ" in text:
                    selected.add("get_weekday")
                elif "âm lịch" in text:
                    selected.add("get_lunar")
                elif "bao nhiêu ngày" in text:
                    selected.add("days_between")
                else:
                    selected.add("get_current_time")
            elif tool_name == "finance":
                selected.add("web_search" if "vàng" in text else "get_exchange_rate")
            else:
                selected.add(tool_name)
    return selected


# Alias cho HybridLLMProvider._select_groq_tools
tool_names_for_query = select_server_tool_names


def tools_for_query(query: str, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Hợp nhất:
    1) Toàn bộ device MCP tools của `device_id` (để LLM hiểu câu nói tự nhiên không cần regex cứng).
    2) Các server tools phù hợp với câu hỏi.
    3) `direct_answer` để LLM có thể trả lời trực tiếp khi không cần gọi tool.
    """
    device_schemas = get_device_mcp_schemas(device_id)
    device_names = {s["function"]["name"] for s in device_schemas}

    server_names = select_server_tool_names(query)
    # Tránh đụng tên nếu thiết bị đã tự khai báo tool cùng tên
    server_schemas = [
        s for s in SERVER_TOOLS_SCHEMA
        if s["function"]["name"] in server_names and s["function"]["name"] not in device_names
    ]

    merged = device_schemas + server_schemas
    merged.append(DIRECT_ANSWER_TOOL)
    return merged


def _parse_arguments(name: str, arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        stripped = arguments.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError as e:
            logger.error(f"Tool {name}: JSON không hợp lệ: {e}")
            raise ValueError(f"Tham số cho {name} không phải JSON hợp lệ.") from e
    return {}


async def execute_tool(
    name: str,
    arguments: Any,
    device_id: Optional[str] = None,
) -> str:
    """Thực thi tool: ưu tiên tool MCP thuộc `device_id`, sau đó mới tới server plugins."""
    if name == "direct_answer":
        try:
            parsed_args = _parse_arguments(name, arguments)
        except ValueError as e:
            logger.warning(f"Tool direct_answer: dùng câu trả lời dự phòng do arguments lỗi: {e}")
            return "Mình chưa rõ ý bạn."
        response = parsed_args.get("response")
        if isinstance(response, str) and response.strip():
            return response
        return "Mình chưa rõ ý bạn."

    try:
        parsed_args = _parse_arguments(name, arguments)
    except ValueError as e:
        return str(e)

    # 1. Tra cứu trong phạm vi tool MCP của thiết bị `device_id`
    if device_id:
        mcp_mgr = get_device_mcp_manager()
        dev_item = mcp_mgr.get_function_item(device_id, name)
        if dev_item is not None:
            try:
                action_resp = await asyncio.wait_for(dev_item.func(**parsed_args), timeout=12.0)
                result_text = getattr(action_resp, "result", action_resp)
                return str(result_text)
            except asyncio.TimeoutError:
                return f"Thiết bị {device_id} phản hồi quá hạn khi gọi '{name}'."
            except Exception as e:
                logger.exception(f"Device MCP tool '{name}' lỗi trên {device_id}")
                return f"Lỗi gọi tool thiết bị '{name}': {e}"

    # 2. Fallback sang server plugin impl
    from app.core.providers.tools import builtin as _impl
    fn = getattr(_impl, f"_tool_{name}", None)
    if not fn:
        logger.warning(f"Tool không tồn tại: {name} (device_id={device_id})")
        return f"Không có tool '{name}'."

    try:
        result = await asyncio.wait_for(fn(**parsed_args), timeout=15.0)
        try:
            return _impl._compact_text(str(result), max_chars=1500)
        except AttributeError:
            return str(result)
    except TypeError as e:
        logger.error(f"Tool {name} sai tham số: {e} | args={parsed_args}")
        return f"Lỗi tham số cho {name}: {e}"
    except Exception as e:
        logger.exception(f"Tool {name} lỗi")
        return f"Lỗi khi chạy {name}: {e}"
"""Function registry + Action/ActionResponse — theo mô hình server gốc."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class Action(enum.IntEnum):
    ERROR = -1
    NOTFOUND = 0
    NONE = 1
    RESPONSE = 2   # trả lời trực tiếp cho user (không qua LLM)
    REQLLM = 3     # gửi kết quả về LLM để sinh câu trả lời tự nhiên
    RECORD = 4     # chỉ ghi nhận, không gọi lại LLM


class ToolType(enum.IntEnum):
    NONE = 1
    WAIT = 2
    CHANGE_SYS_PROMPT = 3
    SYSTEM_CTL = 4
    IOT_CTL = 5
    MCP_CLIENT = 6


@dataclass
class ActionResponse:
    action: Action
    result: str = ""
    response: str = ""
    data: Any = None


@dataclass
class FunctionItem:
    name: str
    description: str
    func: Callable
    type: ToolType = ToolType.WAIT
    parameters: Dict[str, Any] = field(default_factory=dict)


# Registry toàn cục — giống all_function_registry của server gốc
all_function_registry: Dict[str, FunctionItem] = {}


def register_function(
    name: str,
    description: str,
    type: ToolType = ToolType.WAIT,
    parameters: Optional[Dict[str, Any]] = None,
):
    """
    Decorator đăng ký một Python function làm tool cho LLM.

    Ví dụ:
        @register_function(
            name="get_weather",
            description="Tra thời tiết hiện tại",
            parameters={"city": {"type": "string"}},
        )
        async def get_weather(city: str) -> ActionResponse:
            ...
    """
    def decorator(func: Callable):
        schema_params = {
            "type": "object",
            "properties": parameters or {},
            "required": [
                k for k, v in (parameters or {}).items()
                if v.get("required") is True
            ] if parameters else [],
        }
        # Chuẩn hóa required nếu người dùng khai báo kiểu đơn giản
        if parameters:
            schema_params["properties"] = {
                k: {kk: vv for kk, vv in v.items() if kk != "required"}
                for k, v in parameters.items()
            }

        item = FunctionItem(
            name=name,
            description=description,
            func=func,
            type=type,
            parameters=schema_params,
        )
        all_function_registry[name] = item
        return func

    return decorator


class FunctionRegistry:
    """
    Registry theo từng connection — lọc từ all_function_registry
    theo danh sách tool được phép.
    """

    def __init__(self, allowed_names: Optional[set] = None):
        if allowed_names is None:
            self._items = dict(all_function_registry)
        else:
            self._items = {
                k: v for k, v in all_function_registry.items()
                if k in allowed_names
            }

    def get(self, name: str) -> Optional[FunctionItem]:
        return self._items.get(name)

    def all(self) -> List[FunctionItem]:
        return list(self._items.values())

    def to_openai_schema(self) -> List[dict]:
        result = []
        for item in self._items.values():
            result.append({
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            })
        return result

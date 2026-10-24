"""Unified tool framework — tương thích kiến trúc xiaozhi-server gốc."""
from app.core.providers.tools.unified.register import (
    Action,
    ActionResponse,
    ToolType,
    FunctionRegistry,
    register_function,
)
from app.core.providers.tools.unified.unified_tool_handler import UnifiedToolHandler

__all__ = [
    "Action",
    "ActionResponse",
    "ToolType",
    "FunctionRegistry",
    "register_function",
    "UnifiedToolHandler",
]

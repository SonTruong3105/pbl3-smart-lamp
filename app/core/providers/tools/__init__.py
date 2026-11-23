"""Tools package — unified framework + plugins."""
from app.core.providers.tools.unified import (
    Action,
    ActionResponse,
    ToolType,
    FunctionRegistry,
    UnifiedToolHandler,
    register_function,
)
import app.core.providers.tools.plugins  # noqa: F401 — đăng ký tool
import app.core.providers.tools.calendar  # noqa: F401 — đăng ký calendar tools
import app.core.providers.tools.music  # noqa: F401 — đăng ký music tools

__all__ = [
    "Action",
    "ActionResponse",
    "ToolType",
    "FunctionRegistry",
    "UnifiedToolHandler",
    "register_function",
]

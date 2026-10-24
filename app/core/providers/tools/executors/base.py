"""ToolExecutor — interface chung cho mọi loại tool executor."""
from abc import ABC, abstractmethod
from typing import Any, Dict


class ToolExecutor(ABC):
    """Interface mà mọi executor phải triển khai."""

    @abstractmethod
    async def execute(
        self, conn: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """
        Thực thi tool.

        Args:
            conn: ConnectionHandler hiện tại (để truy cập transport, device_id, ...)
            tool_name: Tên tool cần gọi
            arguments: Dict tham số

        Returns:
            ActionResponse hoặc kết quả thô
        """
        ...

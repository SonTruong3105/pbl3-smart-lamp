"""Track active ConnectionHandler cho reminder delivery (unified with DeviceHub)."""
from typing import Any, List, Optional, Tuple

from app.core.device_hub import get_device_hub


async def register(device_id: str, handler: Any) -> None:
    """Đăng ký thiết bị active vào DeviceHub registry."""
    get_device_hub().register_esp32(device_id, handler)


async def unregister(device_id: str, handler: Any = None) -> None:
    """Hủy đăng ký thiết bị."""
    get_device_hub().unregister_esp32(device_id, handler)


async def all_active() -> List[Tuple[str, Any]]:
    """Trả về danh sách (device_id, handler) của các thiết bị đang online."""
    return list(get_device_hub().all_esp32().items())


def get(device_id: str) -> Optional[Any]:
    """Lấy handler theo device_id."""
    return get_device_hub().get_esp32(device_id)
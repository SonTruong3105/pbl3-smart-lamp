"""Binary framing theo firmware Xiaozhi (main/protocols/websocket_protocol.cc).

Firmware dùng network byte order (htons/htonl):
  v1: raw Opus, không có header.
  v2: >HHIII = version, type, reserved, timestamp, payload_size  (16 bytes)
  v3: >BBH   = type, reserved, payload_size                      (4 bytes)
Mặc định firmware dùng v1; version được báo trong hello và header Protocol-Version.
"""
import struct
from typing import Optional


def unwrap_opus_frame(data: bytes, version: int) -> Optional[bytes]:
    """Bỏ header binary protocol, trả về payload Opus (None nếu frame hỏng)."""
    try:
        if version == 2:
            if len(data) < 16:
                return None
            _, _, _, _timestamp, size = struct.unpack(">HHIII", data[:16])
            return data[16:16 + size] if size > 0 else None
        if version == 3:
            if len(data) < 4:
                return None
            _, _, size = struct.unpack(">BBH", data[:4])
            return data[4:4 + size] if size > 0 else None
        return data
    except Exception:
        return None


def wrap_opus_frame(payload: bytes, version: int) -> bytes:
    """Thêm header binary protocol cho chiều server -> device."""
    try:
        if version == 2:
            return struct.pack(">HHIII", version, 0, 0, 0, len(payload)) + payload
        if version == 3:
            return struct.pack(">BBH", 0, 0, len(payload)) + payload
        return payload
    except Exception:
        return payload

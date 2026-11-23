"""Xác thực ESP32 bằng token (HMAC compare_digest)."""
from __future__ import annotations
import hmac, json
from pathlib import Path
from threading import Lock
from loguru import logger

_TOKENS_FILE = Path("data/devices.json")
_lock = Lock()
_cache: dict[str, str] = {}
_mtime: float = 0.0


def _load_tokens() -> dict[str, str]:
    global _cache, _mtime
    if not _TOKENS_FILE.exists(): return {}
    try:
        st = _TOKENS_FILE.stat()
        if st.st_mtime == _mtime: return _cache
        with _lock:
            st = _TOKENS_FILE.stat()
            if st.st_mtime == _mtime: return _cache
            data = json.loads(_TOKENS_FILE.read_text(encoding="utf-8"))
            _cache = {
                str(k): str(v) for k, v in data.items()
                if isinstance(v, str)
                and len(v) >= 32
                and not v.startswith("REPLACE_")
            }
            _mtime = st.st_mtime
            logger.info(f"🔑 Device auth: {len(_cache)} token(s) loaded")
            return _cache
    except Exception as e:
        logger.warning(f"⚠️ Load devices.json lỗi: {e}")
        return _cache or {}


def get_device_token(device_id: str) -> str | None:
    """Return a registered token for server-generated device configuration."""
    if not device_id:
        return None
    return _load_tokens().get(device_id)


def verify_device_token(device_id: str, token: str) -> bool:
    if not device_id or not token: return False
    tokens = _load_tokens()
    expected = tokens.get(device_id)
    if not expected:
        logger.warning(f"⚠️ Device '{device_id}' chưa đăng ký token")
        return False
    return hmac.compare_digest(expected, token)
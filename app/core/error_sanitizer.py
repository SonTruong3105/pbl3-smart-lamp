"""Error sanitization — chống leak secrets ra client.

Học từ AI Chatbot (gemini_agent.speech_error).

Nguyên tắc:
  - Log raw ở mức DEBUG (chỉ server thấy)
  - Trả về client message ĐÃ LỌC
  - Map exception → category (quota/auth/unavailable/timeout/...)
"""
from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "scrub", "sanitize", "sanitize_exception",
    "install",
]

# ─── Patterns chứa secret ──────────────────────────────────────────
_SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*["\']?([^\s"\',;]+)'),
    re.compile(r'(?i)bearer\s+[a-z0-9\-._~+/]{8,}=*'),
    re.compile(r'(?i)sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'https?://[^\s"\']*[:@][^\s"\']*'),   # user:pass@host
    re.compile(r'(?i)authorization\s*[:=]\s*\S+'),
]

_SAFE_MESSAGES = {
    "quota":       "Dịch vụ đã chạm giới hạn. Vui lòng thử lại sau.",
    "auth":        "Không có quyền truy cập. Kiểm tra cấu hình.",
    "unavailable": "Dịch vụ đang quá tải. Thử lại sau.",
    "timeout":     "Quá thời gian chờ. Thử lại sau.",
    "invalid":     "Yêu cầu không hợp lệ.",
    "network":     "Không kết nối được dịch vụ.",
    "internal":    "Đã xảy ra lỗi. Xem log server để biết chi tiết.",
}


def scrub(text: str) -> str:
    """Loại bỏ các pattern nguy hiểm khỏi text."""
    if not text:
        return text or ""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _extract_code(error: Exception) -> Optional[int]:
    for attr in ("status_code", "code", "status"):
        v = getattr(error, attr, None)
        if isinstance(v, int):
            return v
    return None


def sanitize_exception(error: Exception) -> str:
    """Map exception → safe user message."""
    code = _extract_code(error)

    if code == 429:
        return _SAFE_MESSAGES["quota"]
    if code in (401, 403):
        return _SAFE_MESSAGES["auth"]
    if code and 500 <= code < 600:
        return _SAFE_MESSAGES["unavailable"]

    name = type(error).__name__
    if name in ("TimeoutError", "ReadTimeout", "ConnectTimeout",
                "httpx.TimeoutException", "asyncio.TimeoutError"):
        return _SAFE_MESSAGES["timeout"]
    if name in ("ConnectionError", "ConnectError", "OSError",
                "httpx.ConnectError", "httpx.ConnectTimeout"):
        return _SAFE_MESSAGES["network"]
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return _SAFE_MESSAGES["invalid"]

    return _SAFE_MESSAGES["internal"]


def sanitize(error_or_msg) -> str:
    """Accept exception OR str, trả về safe message."""
    if isinstance(error_or_msg, BaseException):
        return sanitize_exception(error_or_msg)
    return scrub(str(error_or_msg))


# ─── Install ────────────────────────────────────────────────────────
_INSTALLED = False


def install() -> bool:
    """Monkey-patch ConnectionHandler._send_error để tự động sanitize."""
    global _INSTALLED
    if _INSTALLED:
        return True

    try:
        from app.core.connection import ConnectionHandler
    except ImportError:
        return False

    orig = ConnectionHandler._send_error
    if getattr(orig, "_xiaozhi_sanitized", False):
        _INSTALLED = True
        return True

    async def _sanitized_send_error(self, message: str):
        # Log raw cho dev (chỉ server thấy)
        try:
            self.log.debug(f"[error raw] {message}")
        except Exception:
            pass
        # Gửi client bản đã lọc
        safe = scrub(message)
        await orig(self, safe)

    _sanitized_send_error._xiaozhi_sanitized = True
    ConnectionHandler._send_error = _sanitized_send_error
    _INSTALLED = True
    return True
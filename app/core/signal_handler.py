"""Signal handler + watchdog: đảm bảo Ctrl+C luôn hủy được."""
import os
import signal
import sys
import threading
import time
from loguru import logger


_shutdown_requested = False
_shutdown_lock = threading.Lock()
_watchdog_started = False


def _force_exit(reason: str, code: int = 1):
    """Force exit — không cleanup, không chờ."""
    try:
        logger.error(f"🚨 FORCE EXIT: {reason}")
    except Exception:
        pass
    try:
        sys.stderr.write(f"\n🚨 FORCE EXIT: {reason}\n")
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def _watchdog_thread(timeout: float = 10.0):
    """Thread độc lập — sau timeout thì force exit."""
    time.sleep(timeout)
    _force_exit(f"shutdown timeout {timeout}s — task không phản hồi")


def _signal_handler(signum, frame):
    """Yêu cầu shutdown ở lần 1; lần 2 hoặc timeout thì thoát cưỡng bức."""
    global _shutdown_requested, _watchdog_started

    with _shutdown_lock:
        if _shutdown_requested:
            _force_exit("Ctrl+C lần 2")
            return

        _shutdown_requested = True
        try:
            logger.warning(
                f"🛑 Nhận signal {signum} — đang shutdown. "
                f"Nhấn Ctrl+C lần nữa để FORCE EXIT."
            )
        except Exception:
            pass

        # Khởi động watchdog
        if not _watchdog_started:
            _watchdog_started = True
            t = threading.Thread(
                target=_watchdog_thread,
                args=(10.0,),
                daemon=True,
                name="shutdown-watchdog",
            )
            t.start()

    # Chuyển signal đầu tiên thành KeyboardInterrupt để runner thực hiện
    # shutdown chính thức thay vì chỉ ghi log rồi tiếp tục chờ.
    try:
        if signum == signal.SIGINT:
            signal.default_int_handler(signum, frame)
    except Exception:
        _force_exit(f"không thể chuyển SIGINT thành KeyboardInterrupt")


def install():
    """Cài signal handler + watchdog cho SIGINT/SIGTERM."""
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        logger.info("🛡️ Signal handler đã cài (double Ctrl+C = force exit)")
    except (ValueError, OSError) as e:
        logger.warning(f"⚠️ Không cài được signal handler: {e}")
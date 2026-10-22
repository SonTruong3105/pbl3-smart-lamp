"""Smart Logging — module string + per-session file."""
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict
from loguru import logger

from app.config import config


LOG_DIR = Path(config.log_dir)
SESSION_LOG_DIR = LOG_DIR / "sessions"

LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _abbrev(name: str) -> str:
    if not name:
        return "00"
    if "_" in name:
        parts = name.split("_")
        return (parts[-1][:2] if parts[-1] else "00").lower()
    return name[:2].lower()


def build_module_string() -> str:
    return (
        _abbrev("silero")
        + _abbrev(config.asr_provider)
        + _abbrev(config.llm_provider)
        + _abbrev(config.tts_provider)
        + _abbrev(config.memory_provider)
        + _abbrev("function_call")
        + "00"
    )


class SessionFileSink:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._files: Dict[str, object] = {}
        self._lock = threading.Lock()

    def _get_file(self, session_id):
        sid = str(session_id)
        if sid not in self._files:
            path = self.base_dir / f"{sid}.log"
            self._files[sid] = open(path, "a", encoding="utf-8")
        return self._files[sid]

    def __call__(self, message):
        try:
            sid = message.record["extra"].get("session_id")
            if sid in (None, "-", 0, "0"):
                return
            with self._lock:
                f = self._get_file(sid)
                f.write(message)
                f.flush()
        except Exception:
            pass

    def close_all(self):
        with self._lock:
            for f in self._files.values():
                try:
                    f.close()
                except Exception:
                    pass
            self._files.clear()


_session_sink: SessionFileSink = None
_logger_initialized = False
_MODULE_STRING = "00000000000000"

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green>|"
    "[<light-blue>{extra[module_string]}</light-blue>]|"
    "[<cyan>{extra[session_short]}</cyan>]|"
    "<level>{level: <7}</level>|"
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} - "
    "v{extra[version]}_{extra[module_string]} - "
    "{name} - {level} - "
    "[session={extra[session_id]}] - "
    "[device={extra[device_id]}] - "
    "{message}"
)


def setup_logging(level: str = None) -> None:
    global _logger_initialized, _MODULE_STRING, _session_sink

    if _logger_initialized:
        return

    _MODULE_STRING = build_module_string()
    level = level or config.log_level

    logger.configure(extra={
        "session_id": "-",
        "session_short": "------",
        "device_id": "-",
        "module_string": _MODULE_STRING,
        "version": config.version,
    })

    logger.remove()

    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    logger.add(
        LOG_DIR / "app.log",
        format=FILE_FORMAT,
        level="DEBUG",
        rotation=f"{config.log_main_rotation_mb} MB",
        retention=config.log_retention_days,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    logger.add(
        LOG_DIR / "errors.log",
        format=FILE_FORMAT,
        level="WARNING",
        rotation=f"{config.log_error_rotation_mb} MB",
        retention=config.log_retention_days * 2,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    _session_sink = SessionFileSink(SESSION_LOG_DIR)
    logger.add(
        _session_sink,
        format=FILE_FORMAT,
        level="DEBUG",
        enqueue=False,
    )

    _logger_initialized = True
    logger.info(
        f"📝 Logging khởi động | level={level} | "
        f"modules={_MODULE_STRING} | dir={LOG_DIR.resolve()}"
    )


def shutdown_logging():
    global _session_sink
    if _session_sink:
        _session_sink.close_all()


def get_session_logger(session_id, device_id: str = "-"):
    sid = session_id if session_id is not None else "-"
    short = f"#{str(sid)[:6]:>6}" if sid != "-" else "------"
    return logger.bind(session_id=sid, session_short=short, device_id=device_id)


def list_session_logs() -> list:
    if not SESSION_LOG_DIR.exists():
        return []
    files = []
    for p in sorted(
        SESSION_LOG_DIR.glob("*.log"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        stat = p.stat()
        files.append({
            "session_id": p.stem,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                "%H:%M %d/%m/%Y"
            ),
        })
    return files


def read_session_log(session_id: str, tail: int = 500) -> str:
    path = SESSION_LOG_DIR / f"{session_id}.log"
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-tail:])


def cleanup_old_logs(days: int = None) -> int:
    from time import time
    days = days or config.log_retention_days
    cutoff = time() - days * 86400
    deleted = 0
    for p in SESSION_LOG_DIR.glob("*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                deleted += 1
        except Exception:
            pass
    return deleted
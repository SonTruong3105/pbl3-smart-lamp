"""Sensor state — lưu giá trị cảm biến từ ESP32 gửi lên."""
import json
import time
from pathlib import Path
from threading import Lock
from typing import Optional


_STATE_FILE = Path("data/sensor_state.json")


_state = {
    "temperature": None,       # °C
    "humidity": None,          # %
    "air_quality_ppm": None,   # MQ135
    "air_quality_level": None, # "tốt" / "kém" / ...
    "light_lux": None,         # lux
    "presence": None,          # bool
    "last_update": 0.0,
}

_lock = Lock()


def _persist():
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(_state, ensure_ascii=False), encoding="utf-8",
        )
    except Exception:
        pass


def _load():
    if _STATE_FILE.exists():
        try:
            loaded = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            with _lock:
                for k, v in loaded.items():
                    if k in _state:
                        _state[k] = v
        except Exception:
            pass


_load()


def update(key: str, value):
    """Cập nhật 1 giá trị. Gọi từ MQTT handler khi ESP32 gửi."""
    with _lock:
        _state[key] = value
        _state["last_update"] = time.time()
    _persist()


def update_bulk(data: dict):
    """Cập nhật nhiều giá trị cùng lúc."""
    with _lock:
        for k, v in data.items():
            if k in _state:
                _state[k] = v
        _state["last_update"] = time.time()
    _persist()


def get(key: str) -> Optional[float]:
    with _lock:
        return _state.get(key)


def get_all() -> dict:
    with _lock:
        return dict(_state)


def is_fresh(max_age_sec: float = 120.0) -> bool:
    """Dữ liệu có mới không (mặc định 2 phút)."""
    with _lock:
        return (time.time() - _state["last_update"]) < max_age_sec

"""DeviceHub — Quản lý tập trung trạng thái thiết bị, kết nối ESP32 và UI subscribers."""
from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from fastapi import WebSocket
from loguru import logger

_STATE_FILE = Path("data/device_state.json")

LAMP_FIELDS = {"on": None, "brightness": None, "cct": None, "kelvin": None, "last_update": 0.0}
SENSOR_KEYS = frozenset({
    "temperature", "humidity", "pm25",
    "light_lux", "lux", "presence", "distance_cm",
})
SENSOR_FIELDS = {**dict.fromkeys(SENSOR_KEYS), "last_update": 0.0}


class DeviceHub:
    def __init__(self, max_events: int = 100):
        self.max_events = max_events
        self._lock = asyncio.Lock()
        self._state_lock = Lock()
        self._persist_lock = Lock()

        # Kết nối & Subscribers
        self._esp32_handlers: Dict[str, Any] = {}
        self._chat_links: Dict[str, Tuple[str, Any]] = {}      # web_id -> (device_id, chat_ws)
        self._sync_subs: Dict[str, Set[WebSocket]] = {}        # device_id -> set(dashboard_ws)
        self._observers: Dict[str, Set[WebSocket]] = {}        # device_id -> set(observe_ws)
        self._active_devices: Set[str] = set()

        # Cache trạng thái & Lịch sử sự kiện
        self._lamp: Dict[str, dict] = {}
        self._sensors: Dict[str, dict] = {}
        self._events: Dict[str, Deque[dict]] = {}
        self._legacy_lamp: dict = dict(LAMP_FIELDS)
        self._legacy_sensors: dict = dict(SENSOR_FIELDS)

        self._load_state()

    # =========================================================================
    # 1. PERSISTENCE (Lưu/tải trạng thái đèn & cảm biến)
    # =========================================================================
    def _load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                with self._state_lock:
                    for did, st in (raw.get("lamp") or {}).items():
                        self._lamp[str(did)] = {**LAMP_FIELDS, **{k: v for k, v in st.items() if k in LAMP_FIELDS}}
                    for did, st in (raw.get("sensors") or {}).items():
                        self._sensors[str(did)] = {**SENSOR_FIELDS, **{k: v for k, v in st.items() if k in SENSOR_FIELDS}}
                return
            except Exception:
                pass

        for old_file, target_map, fields in (
            (Path("data/lamp_state.json"), self._lamp, LAMP_FIELDS),
            (Path("data/sensor_state.json"), self._sensors, SENSOR_FIELDS),
        ):
            if old_file.exists():
                try:
                    raw = json.loads(old_file.read_text(encoding="utf-8"))
                    with self._state_lock:
                        for did, st in (raw.get("devices") or {}).items():
                            if isinstance(st, dict):
                                target_map[str(did)] = {**fields, **{k: v for k, v in st.items() if k in fields}}
                except Exception:
                    pass

    def _persist_state(self) -> None:
        try:
            with self._persist_lock:
                with self._state_lock:
                    payload = json.dumps(
                        {"lamp": self._lamp, "sensors": self._sensors},
                        ensure_ascii=False,
                    )
                _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                _STATE_FILE.write_text(payload, encoding="utf-8")
        except Exception:
            pass

    # =========================================================================
    # 2. LAMP & SENSOR STATE
    # =========================================================================
    def update_lamp(self, data: dict, device_id: Optional[str] = None) -> None:
        if not isinstance(data, dict):
            return
        with self._state_lock:
            target = self._lamp.setdefault(device_id, dict(LAMP_FIELDS)) if device_id else self._legacy_lamp
            for key in ("on", "brightness", "cct", "kelvin"):
                if key in data:
                    target[key] = data[key]
            target["last_update"] = time.time()
            if device_id:
                self._legacy_lamp = dict(target)
        self._persist_state()

    def get_lamp(self, device_id: Optional[str] = None) -> dict:
        with self._state_lock:
            st = self._lamp.get(device_id) if device_id else self._legacy_lamp
            return dict(st) if st else dict(LAMP_FIELDS)

    def update_sensors(self, data: dict, device_id: Optional[str] = None) -> None:
        if not isinstance(data, dict):
            return
        now = time.time()
        with self._state_lock:
            target = self._sensors.setdefault(device_id, dict(SENSOR_FIELDS)) if device_id else self._legacy_sensors
            for key, value in data.items():
                if key in SENSOR_KEYS:
                    target[key] = value
                if key in ("lux", "light_lux"):
                    target["light_lux"] = value
                    target["lux"] = value
            target["last_update"] = now
            if device_id:
                self._legacy_sensors = dict(target)
        self._persist_state()

    def get_sensor(self, key: str, device_id: Optional[str] = None) -> Optional[float]:
        with self._state_lock:
            st = self._sensors.get(device_id) if device_id else self._legacy_sensors
            if not st:
                return None
            if key == "lux" and st.get("lux") is None:
                return st.get("light_lux")
            if key == "light_lux" and st.get("light_lux") is None:
                return st.get("lux")
            return st.get(key)

    def get_all_sensors(self, device_id: Optional[str] = None) -> dict:
        with self._state_lock:
            st = self._sensors.get(device_id) if device_id else self._legacy_sensors
            return dict(st) if st else dict(SENSOR_FIELDS)

    def is_sensor_fresh(self, max_age_sec: float = 120.0, device_id: Optional[str] = None) -> bool:
        with self._state_lock:
            st = self._sensors.get(device_id) if device_id else self._legacy_sensors
            if not st:
                return False
            last = st.get("last_update", 0)
            return bool(last and time.time() - last < max_age_sec)

    # =========================================================================
    # 3. ESP32 REGISTRATION & ONLINE STATUS
    # =========================================================================
    def register_esp32(self, device_id: str, handler: Any) -> None:
        self._esp32_handlers[device_id] = handler
        self._active_devices.add(device_id)

    def unregister_esp32(self, device_id: str, handler: Any = None) -> None:
        current = self._esp32_handlers.get(device_id)
        if current is not None and (handler is None or current is handler):
            self._esp32_handlers.pop(device_id, None)
            self._active_devices.discard(device_id)

    def get_esp32(self, device_id: str) -> Optional[Any]:
        return self._esp32_handlers.get(device_id)

    def all_esp32(self) -> Dict[str, Any]:
        return dict(self._esp32_handlers)

    def register_active(self, device_id: str) -> None:
        self._active_devices.add(device_id)

    def unregister_active(self, device_id: str) -> None:
        self._active_devices.discard(device_id)

    def register_active_device(self, device_id: str) -> None:
        self.register_active(device_id)

    def unregister_active_device(self, device_id: str) -> None:
        self.unregister_active(device_id)

    def get_active_devices(self) -> List[str]:
        return list(self._active_devices)

    def _get_mcp_online_ids(self) -> Set[str]:
        try:
            from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
            mcp_mgr = get_device_mcp_manager()
            if hasattr(mcp_mgr, "get_online_device_ids"):
                return set(mcp_mgr.get_online_device_ids())
            return {
                did for did, tr in getattr(mcp_mgr, "_transports", {}).items()
                if tr is not None and getattr(tr, "is_connected", True)
            }
        except Exception:
            return set()

    def is_online(self, device_id: str) -> bool:
        if device_id in self._esp32_handlers or device_id in self._active_devices:
            return True
        if device_id in self._get_mcp_online_ids():
            return True
        try:
            from app.core.mqtt_server import get_mqtt_manager
            mgr = get_mqtt_manager()
            if device_id in mgr.sessions:
                return True
            dev = mgr.control_devices.get(device_id)
            if dev and (asyncio.get_running_loop().time() - dev.get("last_seen", 0) <= 90.0):
                return True
        except Exception:
            pass
        return False

    def online_devices(self) -> Set[str]:
        online = set(self._esp32_handlers.keys()) | set(self._active_devices) | self._get_mcp_online_ids()
        try:
            from app.core.mqtt_server import get_mqtt_manager
            mgr = get_mqtt_manager()
            now = asyncio.get_running_loop().time()
            online |= set(mgr.sessions) | {
                did for did, st in mgr.control_devices.items()
                if now - st.get("last_seen", 0) <= 90.0
            }
        except Exception:
            pass
        return online

    # =========================================================================
    # 4. WEB CHAT LINKS & DASHBOARD / OBSERVER SUBSCRIBERS
    # =========================================================================
    def link_chat(self, web_id: str, device_id: str, chat_ws: Any) -> None:
        self._chat_links[web_id] = (device_id, chat_ws)

    def unlink_chat(self, web_id: str) -> None:
        self._chat_links.pop(web_id, None)

    def get_chat_by_web(self, web_id: str) -> Optional[Tuple[str, Any]]:
        return self._chat_links.get(web_id)

    def get_chats_by_device(self, device_id: str) -> List[Tuple[str, Any]]:
        return [(wid, ws) for wid, (did, ws) in self._chat_links.items() if did == device_id]

    def all_chat_links(self) -> Dict[str, Tuple[str, Any]]:
        return dict(self._chat_links)

    async def subscribe_sync(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._sync_subs.setdefault(device_id, set()).add(ws)

    async def unsubscribe_sync(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            s = self._sync_subs.get(device_id)
            if s:
                s.discard(ws)
                if not s:
                    self._sync_subs.pop(device_id, None)

    async def broadcast_sync(self, device_id: str, msg_type: str, data: dict) -> int:
        async with self._lock:
            targets = list(self._sync_subs.get(device_id, ()))
        if not targets:
            return 0
        message = {"type": msg_type, "data": data}
        sent = 0
        for ws in targets:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:
                await self.unsubscribe_sync(device_id, ws)
        return sent

    async def subscribe_observer(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._observers.setdefault(device_id, set()).add(ws)
            logger.info(f"📡 Observer subscribed: {device_id}")

    async def unsubscribe_observer(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            s = self._observers.get(device_id)
            if s:
                s.discard(ws)
                if not s:
                    self._observers.pop(device_id, None)
            logger.info(f"📡 Observer unsubscribed: {device_id}")

    async def broadcast_event(self, device_id: str, event: dict) -> None:
        if event.get("type") in ("audio", "user_wav"):
            return
        async with self._lock:
            observers = list(self._observers.get(device_id, ()))
            hist = self._events.setdefault(device_id, deque(maxlen=self.max_events))
            hist.append(event)
        for ws in observers:
            try:
                await ws.send_json(event)
            except Exception:
                await self.unsubscribe_observer(device_id, ws)

    def get_event_history(self, device_id: str) -> List[dict]:
        return list(self._events.get(device_id, ()))


_device_hub: Optional[DeviceHub] = None


def get_device_hub() -> DeviceHub:
    global _device_hub
    if _device_hub is None:
        _device_hub = DeviceHub()
    return _device_hub


def parse_mcp_result(result: Optional[dict]) -> Optional[dict]:
    """Trích dict dữ liệu từ kết quả _send_mcp_command / MCP JSON-RPC."""
    if not isinstance(result, dict):
        return None
    reply = result.get("reply")
    if isinstance(reply, dict):
        content = reply.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        parsed = json.loads(item["text"])
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
        return reply
    if isinstance(reply, str):
        try:
            parsed = json.loads(reply)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None
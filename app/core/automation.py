"""Automation — rule engine + adaptive lighting + AI visual state.

Gộp từ: automation.py (rule-based) + lamp_automation.py (adaptive + visual).
Cả 2 đều điều khiển đèn qua MCP command → gộp để dễ bảo trì.
"""
import asyncio
import time
from datetime import datetime
from loguru import logger

from app.config import config
from app.core.device_hub import get_device_hub


def _rgb_to_color_temp(r: int, g: int, b: int) -> int:
    """Đèn board là warm/cool 2 kênh — không có tool Lamp.SetRGB.

    Quy đổi RGB về tỷ lệ lạnh 0..100 mà firmware hiểu (0=ấm, 100=lạnh).
    """
    r, g, b = (max(0, min(255, int(x))) for x in (r, g, b))
    warmth = (r - b) / 255.0  # -1 (lạnh) .. +1 (ấm)
    return int(round((1.0 - warmth) * 50))


# ═══ RULE ENGINE (from automation.py) ═══
RULES = [
    {
        "name": "Bat den khi co nguoi + toi",
        "condition": lambda: (
            _safe_get("presence") is True
            and (_safe_get("light_lux") or 9999) < 50
        ),
        "action": lambda: _do_mcp("Lamp.SetBrightness", {"value": 60}),
        "cooldown_sec": 300,
        "_last_fired": 0,
    },
    {
        "name": "Canh bao bui min PM2.5 cao (den do)",
        "condition": lambda: (_safe_get("pm25") or 0) > 55,
        "action": lambda: _do_mcp("Lamp.SetColorTemp", {"value": _rgb_to_color_temp(255, 0, 0)}),
        "cooldown_sec": 600,
        "_last_fired": 0,
    },
    {
        "name": "Canh bao nong (den cam)",
        "condition": lambda: (_safe_get("temperature") or 0) > 35,
        "action": lambda: _do_mcp("Lamp.SetColorTemp", {"value": _rgb_to_color_temp(255, 140, 0)}),
        "cooldown_sec": 900,
        "_last_fired": 0,
    },
]

# ═══ ADAPTIVE TIME PROFILE (from lamp_automation.py) ═══
_TIME_PROFILE = [
    (range(6, 9),   (70, 40),  "Buoi sang - am nhe"),
    (range(9, 12),  (90, 60),  "Buoi trua - tu nhien"),
    (range(12, 14), (100, 70), "Dau chieu - sang"),
    (range(14, 18), (80, 60),  "Chieu - diu"),
    (range(18, 21), (70, 40),  "Toi - am ap"),
    (range(21, 24), (40, 20),  "Khuya - mo"),
    (range(0, 6),   (10, 10),  "Ngu - den ngu"),
]

# ═══ AI VISUAL STATE (from lamp_automation.py) ═══
_AI_STATE = {
    "listening": (100, 50, 0),
    "thinking":  (100, 0, 100),
    "speaking":  (0, 100, 60),
    "error":     (100, 0, 0),
    "idle":      (50, 50, 40),
}
_last_state = {"state": None}
_background_tasks: set[asyncio.Task] = set()


# ═══ HELPERS ═══
def _safe_get(key: str):
    try:
        hub = get_device_hub()
        if not hub.is_sensor_fresh(max_age_sec=300):
            return None
        return hub.get_sensor(key)
    except Exception:
        return None


async def _do_mcp(method: str, params: dict, timeout: float = 2.0, raise_on_error: bool = False):
    from app.core.providers.tools.builtin import _send_mcp_command
    try:
        return await _send_mcp_command(method, params, timeout=timeout)
    except Exception as e:
        logger.debug(f"Automation MCP loi ({method}): {e}")
        if raise_on_error:
            raise
        return None


# ═══ RULE ENGINE ═══
async def check_rules():
    now = time.time()
    for rule in RULES:
        if now - rule["_last_fired"] < rule["cooldown_sec"]:
            continue
        try:
            if rule["condition"]() and rule["action"]:
                await rule["action"]()
                rule["_last_fired"] = now
                logger.info(f"Automation: {rule['name']}")
        except Exception as e:
            logger.warning(f"Rule '{rule['name']}' loi: {e}")


# ═══ ADAPTIVE LIGHTING ═══
async def apply_time_profile(log=None) -> bool:
    h = datetime.now().hour
    for hours, (bright, ct), label in _TIME_PROFILE:
        if h in hours:
            try:
                await _do_mcp("Lamp.SetBrightness", {"value": bright}, timeout=2.0, raise_on_error=True)
                await _do_mcp("Lamp.SetColorTemp", {"value": ct}, timeout=2.0, raise_on_error=True)
                if log:
                    log.info(f"Adaptive: {label} | h={h}")
                return True
            except Exception as e:
                if log:
                    log.warning(f"Adaptive lighting loi: {e}")
                return False
    return False


# ═══ AI VISUAL STATE ═══
async def set_ai_visual_state(state: str, log=None):
    if not config._get("lamp_automation", "ai_visual_state", default=False):
        return
    if state not in _AI_STATE:
        return
    if _last_state.get("state") == state:
        return
    _last_state["state"] = state
    task = asyncio.create_task(_do_set_visual_state(state, log))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _do_set_visual_state(state: str, log=None):
    r, g, b = _AI_STATE[state]
    try:
        await asyncio.wait_for(
            _do_mcp("Lamp.SetColorTemp", {"value": _rgb_to_color_temp(r, g, b)}, timeout=1.0, raise_on_error=True),
            timeout=1.5,
        )
    except Exception as e:
        if log:
            log.debug(f"Visual state '{state}' loi: {e}")


def reset_visual_state():
    _last_state["state"] = None
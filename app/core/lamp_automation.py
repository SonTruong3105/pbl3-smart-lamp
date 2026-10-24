"""Lamp automation — adaptive lighting + visual feedback AI state."""
from datetime import datetime
from loguru import logger

_TIME_PROFILE = [
    (range(6, 9),   (70, 40),  "Buoi sang - am nhe"),
    (range(9, 12),  (90, 60),  "Buoi trua - tu nhien"),
    (range(12, 14), (100, 70), "Dau chieu - sang"),
    (range(14, 18), (80, 60),  "Chieu - diu"),
    (range(18, 21), (70, 40),  "Toi - am ap"),
    (range(21, 24), (40, 20),  "Khuya - mo"),
    (range(0, 6),   (10, 10),  "Ngu - den ngu"),
]

async def apply_time_profile(log=None) -> bool:
    from app.core.providers.tools.impl import _send_mcp_command
    h = datetime.now().hour
    for hours, (bright, ct), label in _TIME_PROFILE:
        if h in hours:
            try:
                await _send_mcp_command("Lamp.SetBrightness", {"value": bright}, timeout=2.0)
                await _send_mcp_command("Lamp.SetColorTemp", {"value": ct}, timeout=2.0)
                if log:
                    log.info(f"Adaptive: {label} | h={h}")
                return True
            except Exception as e:
                if log:
                    log.warning(f"Adaptive lighting loi: {e}")
                return False
    return False

_AI_STATE = {
    "listening": (100, 50, 0),
    "thinking":  (100, 0, 100),
    "speaking":  (0, 100, 60),
    "error":     (100, 0, 0),
    "idle":      (50, 50, 40),
}

_last_state = {"state": None}

async def set_ai_visual_state(state: str, log=None):
    if state not in _AI_STATE:
        return
    if _last_state.get("state") == state:
        return
    _last_state["state"] = state
    import asyncio
    asyncio.create_task(_do_set_visual_state(state, log))

async def _do_set_visual_state(state: str, log=None):
    import asyncio
    from app.core.providers.tools.impl import _send_mcp_command
    r, g, b = _AI_STATE[state]
    try:
        await asyncio.wait_for(
            _send_mcp_command("Lamp.SetRGB", {"r": r, "g": g, "b": b}, timeout=1.0),
            timeout=1.5,
        )
    except Exception as e:
        if log:
            log.debug(f"Visual state '{state}' loi: {e}")

def reset_visual_state():
    _last_state["state"] = None

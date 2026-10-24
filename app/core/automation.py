"""Automation rules — if-this-then-that cho den."""
import time
from loguru import logger

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
        "name": "Canh bao khong khi kem (den do)",
        "condition": lambda: (_safe_get("air_quality_ppm") or 0) > 2000,
        "action": lambda: _do_mcp("Lamp.SetRGB", {"r": 255, "g": 0, "b": 0}),
        "cooldown_sec": 600,
        "_last_fired": 0,
    },
    {
        "name": "Canh bao nong (den cam)",
        "condition": lambda: (_safe_get("temperature") or 0) > 35,
        "action": lambda: _do_mcp("Lamp.SetRGB", {"r": 255, "g": 140, "b": 0}),
        "cooldown_sec": 900,
        "_last_fired": 0,
    },
]


def _safe_get(key: str):
    try:
        from app.core.providers.tools import sensor_state
        if not sensor_state.is_fresh(max_age_sec=300):
            return None
        return sensor_state.get(key)
    except Exception:
        return None


async def _do_mcp(method: str, params: dict):
    from app.core.providers.tools.impl import _send_mcp_command
    try:
        await _send_mcp_command(method, params, timeout=2.0)
    except Exception as e:
        logger.debug(f"Automation MCP loi: {e}")


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

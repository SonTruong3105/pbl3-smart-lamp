"""Scheduler cho automation den. Can: pip install apscheduler."""
from loguru import logger

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    AsyncIOScheduler = None
    CronTrigger = None

_scheduler = None


def get_scheduler():
    global _scheduler
    if not HAS_APSCHEDULER:
        return None
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    return _scheduler


async def add_lamp_schedule(
    hour: int, minute: int, action: str, *, device_id: str | None = None, **params,
):
    from app.core.providers.tools.builtin import _send_mcp_command
    sched = get_scheduler()
    if sched is None:
        raise RuntimeError("APScheduler chua cai. Chay: pip install apscheduler")

    async def _job():
        try:
            if action == "turn_on":
                result = await _send_mcp_command("Lamp.TurnOn", device_id=device_id)
            elif action == "turn_off":
                result = await _send_mcp_command("Lamp.TurnOff", device_id=device_id)
            elif action == "set_brightness":
                result = await _send_mcp_command(
                    "Lamp.SetBrightness", {"value": params.get("value", 50)},
                    device_id=device_id,
                )
            elif action == "set_scene":
                from app.core.providers.tools.scenes import _tool_set_scene
                result = await _tool_set_scene(params.get("scene", ""), device_id=device_id)
            else:
                raise ValueError(f"Unsupported schedule action: {action}")
            if isinstance(result, dict) and not result.get("ok"):
                raise RuntimeError(result.get("error") or "Device command failed")
            logger.info(f"Schedule fired: {action} at {hour:02d}:{minute:02d}")
        except Exception as e:
            logger.warning(f"Schedule job loi: {e}")

    target = device_id or "single-device"
    job_id = f"lamp_{target}_{hour:02d}{minute:02d}_{action}"
    sched.add_job(
        _job, CronTrigger(hour=hour, minute=minute),
        id=job_id, replace_existing=True,
    )
    logger.info(f"Da dat lich: {hour:02d}:{minute:02d} -> {action}")
    return job_id


def list_schedules() -> list:
    sched = get_scheduler()
    if sched is None:
        return []
    return [
        {"id": j.id, "next_run": str(j.next_run_time) if j.next_run_time else None}
        for j in sched.get_jobs()
    ]

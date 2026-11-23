"""Real-time reminder engine — in-memory index + adaptive tick + ACK-based.

Thay the calendar_reminder.py (tick 10s, DB query moi lan).
Latency < 1s. Retry khi device offline. ACK mark played.
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, and_

from app.database import AsyncSessionLocal
from app.models import CalendarEvent, CalendarReminder
from app.repositories import calendar as cal
from app.core import connection_registry

TZ = timezone(timedelta(hours=7))
ACK_TIMEOUT_SEC = 30.0
MAX_RETRIES = 3
IDLE_SLEEP_SEC = 15.0
MIN_SLEEP_SEC = 0.5


class ReminderEngine:
    def __init__(self):
        self._index: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._stats = {"played": 0, "failed": 0, "retries": 0}

    def _on_calendar_change(self):
        if self._running:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.reload())
            except Exception:
                pass

    async def start(self) -> None:
        if self._running: return
        self._running = True
        cal.add_change_listener(self._on_calendar_change)
        await self.reload()
        self._task = asyncio.create_task(self._loop(), name="reminder-engine")
        logger.info(f"⏰ ReminderEngine started | {len(self._index)} upcoming")

    async def stop(self) -> None:
        self._running = False
        cal.remove_change_listener(self._on_calendar_change)
        self._wake.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except (asyncio.CancelledError, Exception): pass
            self._task = None
        logger.info(f"⏰ ReminderEngine stopped | stats={self._stats}")

    async def reload(self) -> None:
        """Reload index từ DB. Gọi khi event CRUD hoặc ESP32 connect."""
        now = datetime.now(TZ)
        try:
            async with AsyncSessionLocal() as db:
                due = await cal.due_reminders(db, now, lookahead_hours=24)
        except Exception as e:
            logger.exception(f"reload failed: {e}")
            return
        async with self._lock:
            old = set(self._index)
            new = {}
            for r in due:
                rid = r["id"]
                # Preserve in-memory retry state across a reload, but let terminal
                # database states prevent notifications after process restarts.
                if rid in self._index:
                    new[rid] = self._index[rid]
                    continue
                start = datetime.fromisoformat(
                    f"{r['event']['date']}T{r['event']['start_time']}"
                ).replace(tzinfo=TZ)
                remind_at = start - timedelta(minutes=r["event"].get("remind_minutes", 0))
                new[rid] = {
                    "id": rid,
                    "reminder_id": rid,
                    "event": r["event"],
                    "text": r["text"],
                    "remind_at": remind_at,
                    "expires_at": datetime.fromisoformat(r["expires_at"]),
                    "acked": False,
                    "retries": 0,
                    "last_sent": 0.0,
                    "last_attempt": 0.0,
                }
            self._index = new
        self._wake.set()
        added = len(set(new) - old)
        removed = len(old - set(new))
        if added or removed:
            logger.info(f"⏰ Index reloaded | +{added} -{removed} total={len(new)}")

    async def ack(self, reminder_id: str) -> bool:
        """ESP32 gọi khi nhận reminder. Mark played."""
        async with self._lock:
            r = self._index.pop(reminder_id, None)
            if not r: return False
            self._stats["played"] += 1
        try:
            async with AsyncSessionLocal() as db:
                await cal.mark_reminder(db, reminder_id, "played")
            logger.info(f"✅ Reminder acked: {reminder_id} — '{r['event']['title']}'")
            return True
        except Exception as e:
            logger.warning(f"ack save failed: {e}")
            return False

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
                sleep_sec = await self._compute_sleep()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=sleep_sec)
                    self._wake.clear()
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"tick error: {e}")
                await asyncio.sleep(2.0)

    async def _tick(self) -> None:
        now = datetime.now(TZ)
        due: list[dict] = []
        async with self._lock:
            for r in list(self._index.values()):
                if r["acked"]: continue
                if now >= r["expires_at"]:
                    # Event đã qua, không cần phát nữa
                    self._index.pop(r["id"], None)
                    self._stats["failed"] += 1
                    try:
                        async with AsyncSessionLocal() as db:
                            await cal.mark_reminder(db, r["id"], "failed")
                    except Exception: pass
                    continue
                if r["remind_at"] <= now:
                    last_sent = r["last_sent"]
                    last_attempt = r["last_attempt"]
                    retry_clock = last_sent or last_attempt
                    if retry_clock:
                        elapsed = time.monotonic() - retry_clock
                        if elapsed < ACK_TIMEOUT_SEC:
                            continue
                        if last_sent and r["retries"] >= MAX_RETRIES:
                            self._index.pop(r["id"], None)
                            self._stats["failed"] += 1
                            try:
                                async with AsyncSessionLocal() as db:
                                    await cal.mark_reminder(db, r["id"], "failed")
                            except Exception:
                                pass
                            continue
                    due.append(dict(r))
        if not due: return
        handlers = await connection_registry.all_active()
        for r in due:
            await self._dispatch(r, handlers)

    async def _dispatch(self, r: dict, handlers: list) -> None:
        r.setdefault("reminder_id", r["id"])
        ev_dev = r["event"].get("device_id")
        sent_to = []
        for device_id, handler in handlers:
            if ev_dev is not None and ev_dev != device_id:
                continue
            try:
                await handler.notify_reminder(r)
                sent_to.append(device_id)
            except Exception as e:
                logger.warning(f"notify →{device_id} failed: {e}")

        now_mono = time.monotonic()
        async with self._lock:
            live = self._index.get(r["id"])
            if not live:
                return
            live["last_attempt"] = now_mono
            if sent_to:
                live["last_sent"] = now_mono
                live["retries"] += 1
                self._stats["retries"] += 1
                logger.debug(f"⏰ sent #{live['retries']} →{sent_to}")
            elif handlers:
                # A handler exists but delivery failed; wait before retrying.
                live["last_sent"] = now_mono
            # No matching/active handler is transient (e.g. device offline).

    async def _compute_sleep(self) -> float:
        now = datetime.now(TZ)
        async with self._lock:
            pending = [r for r in self._index.values() if not r["acked"]]
        if not pending:
            return IDLE_SLEEP_SEC
        next_at = min(r["remind_at"] for r in pending)
        diff = (next_at - now).total_seconds()
        return max(MIN_SLEEP_SEC, min(diff, IDLE_SLEEP_SEC))

    def stats(self) -> dict:
        return {**self._stats, "pending": len(self._index)}


# Singleton
_engine: Optional[ReminderEngine] = None

def get_engine() -> ReminderEngine:
    global _engine
    if _engine is None:
        _engine = ReminderEngine()
    return _engine
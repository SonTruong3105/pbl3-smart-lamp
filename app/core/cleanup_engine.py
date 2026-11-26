"""Auto-cleanup engine — TTL cho reminders/events, LRU cho music cache.

Chạy mỗi giờ. Config-driven. Xoá an toàn (best-effort, log lỗi).
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import delete, select, func

from app.database import AsyncSessionLocal
from app.models import CalendarEvent, CalendarReminder

TZ = timezone(timedelta(hours=7))


class CleanupEngine:
    def __init__(self, interval_sec: int = 3600,
                 reminder_retention_days: int = 7,
                 event_retention_days: int = 30,
                 music_cache_dir: str = "data/music_cache",
                 music_max_mb: int = 500,
                 music_max_files: int = 100):
        self.interval = interval_sec
        self.rem_days = reminder_retention_days
        self.ev_days = event_retention_days
        self.music_dir = Path(music_cache_dir)
        self.music_max_bytes = music_max_mb * 1024 * 1024
        self.music_max_files = music_max_files
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_stats: dict = {}

    async def start(self) -> None:
        if self._running: return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cleanup-engine")
        logger.info(f"🧹 CleanupEngine started | interval={self.interval}s "
                    f"rem_ttl={self.rem_days}d ev_ttl={self.ev_days}d")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try: await self._task
            except (asyncio.CancelledError, Exception): pass
            self._task = None
        logger.info(f"🧹 CleanupEngine stopped")

    async def _loop(self) -> None:
        # Chờ 5 phút lần đầu để server ổn định
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"cleanup error: {e}")
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break

    async def run_once(self) -> dict:
        stats = {
            "reminders_deleted": 0,
            "events_deleted": 0,
            "music_deleted": 0,
            "music_freed_mb": 0.0,
        }
        try:
            stats.update(await self._cleanup_reminders())
            stats.update(await self._cleanup_events())
            stats.update(await self._cleanup_music())
            self._last_stats = {**stats, "at": datetime.now(TZ).isoformat()}
            if any(v for k, v in stats.items() if k.endswith(("_deleted", "_mb")) and v):
                logger.info(f"🧹 Cleanup: {stats}")
        except Exception as e:
            logger.exception(f"cleanup run failed: {e}")
        return stats

    async def _cleanup_reminders(self) -> dict:
        cutoff = datetime.utcnow() - timedelta(days=self.rem_days)
        try:
            async with AsyncSessionLocal() as db:
                # Xoá reminder đã terminal và cũ
                r = await db.execute(delete(CalendarReminder).where(
                    CalendarReminder.status.in_(("played", "failed", "cancelled")),
                    CalendarReminder.updated_at < cutoff,
                ))
                count = r.rowcount or 0
                # Xoá reminder active=0 (bị invalidate) cũ
                r2 = await db.execute(delete(CalendarReminder).where(
                    CalendarReminder.active == 0,
                    CalendarReminder.updated_at < cutoff,
                ))
                count += r2.rowcount or 0
                await db.commit()
            return {"reminders_deleted": count}
        except Exception as e:
            logger.warning(f"cleanup reminders failed: {e}")
            return {"reminders_deleted": 0}

    async def _cleanup_events(self) -> dict:
        cutoff = (datetime.now(TZ) - timedelta(days=self.ev_days)).strftime("%Y-%m-%d")
        try:
            async with AsyncSessionLocal() as db:
                # Xoá reminder con trước (FK)
                old_event_ids = (
                    await db.execute(select(CalendarEvent.id)
                        .where(CalendarEvent.date < cutoff))
                ).scalars().all()
                if old_event_ids:
                    await db.execute(delete(CalendarReminder)
                        .where(CalendarReminder.event_id.in_(old_event_ids)))
                r = await db.execute(delete(CalendarEvent)
                    .where(CalendarEvent.date < cutoff))
                count = r.rowcount or 0
                await db.commit()
            return {"events_deleted": count}
        except Exception as e:
            logger.warning(f"cleanup events failed: {e}")
            return {"events_deleted": 0}

    async def _cleanup_music(self) -> dict:
        if not self.music_dir.exists():
            return {"music_deleted": 0, "music_freed_mb": 0.0}
        try:
            # Sweep both legacy MP3 cache entries and current Ogg tracks.
            files = list(self.music_dir.glob("*.mp3")) + list(self.music_dir.glob("*.ogg"))
            if not files:
                return {"music_deleted": 0, "music_freed_mb": 0.0}

            total = sum(f.stat().st_size for f in files if f.is_file())
            count = len(files)
            to_delete = []

            # Rule 1: vượt số file → xoá LRU (cũ nhất theo atime)
            if count > self.music_max_files:
                files_sorted = sorted(
                    files,
                    key=lambda f: f.stat().st_atime if f.exists() else 0,
                )
                excess = count - self.music_max_files
                to_delete.extend(files_sorted[:excess])

            # Rule 2: vượt size → xoá LRU cho đến khi đủ
            if total > self.music_max_bytes and to_delete:
                pass  # already over
            elif total > self.music_max_bytes:
                files_sorted = sorted(
                    files,
                    key=lambda f: f.stat().st_atime if f.exists() else 0,
                )
                for f in files_sorted:
                    if total <= self.music_max_bytes:
                        break
                    try:
                        sz = f.stat().st_size
                        to_delete.append(f)
                        total -= sz
                    except Exception: pass

            freed = 0
            for f in set(to_delete):
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    freed += sz
                except Exception as e:
                    logger.debug(f"delete {f} failed: {e}")
            return {
                "music_deleted": len(set(to_delete)),
                "music_freed_mb": round(freed / 1024 / 1024, 2),
            }
        except Exception as e:
            logger.warning(f"cleanup music failed: {e}")
            return {"music_deleted": 0, "music_freed_mb": 0.0}

    def stats(self) -> dict:
        return dict(self._last_stats)


_engine: Optional[CleanupEngine] = None

def get_engine() -> CleanupEngine:
    global _engine
    if _engine is None:
        _engine = CleanupEngine()
    return _engine
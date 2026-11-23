import asyncio
import time
from datetime import datetime, timedelta

from app.core import reminder_engine


def _reminder():
    now = datetime.now(reminder_engine.TZ)
    return {
        "id": "event-1:1",
        "event": {
            "id": "event-1",
            "title": "Test",
            "date": now.date().isoformat(),
            "start_time": (now - timedelta(minutes=1)).strftime("%H:%M"),
            "end_time": (now + timedelta(minutes=30)).strftime("%H:%M"),
            "remind_minutes": 0,
            "device_id": "device-1",
        },
        "text": "Reminder",
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
    }


def test_tick_waits_for_ack_timeout_before_resending(monkeypatch):
    async def run():
        engine = reminder_engine.ReminderEngine()
        payload = _reminder()
        sent = []

        class Handler:
            async def notify_reminder(self, reminder):
                sent.append(reminder)

        async def active():
            return [("device-1", Handler())]

        monkeypatch.setattr(reminder_engine.connection_registry, "all_active", active)
        monkeypatch.setattr(reminder_engine, "ACK_TIMEOUT_SEC", 30)
        engine._index[payload["id"]] = {
            **payload,
            "remind_at": datetime.now(reminder_engine.TZ) - timedelta(seconds=1),
            "expires_at": datetime.now(reminder_engine.TZ) + timedelta(minutes=5),
            "retries": 1,
            "last_sent": time.monotonic(),
            "last_attempt": time.monotonic(),
            "acked": False,
        }

        await engine._tick()
        assert sent == []

        engine._index[payload["id"]]["last_sent"] = time.monotonic() - 31
        await engine._tick()
        assert len(sent) == 1
        assert sent[0]["reminder_id"] == payload["id"]
        assert engine._index[payload["id"]]["retries"] == 2

    asyncio.run(run())


def test_offline_device_does_not_fail_reminder(monkeypatch):
    async def run():
        engine = reminder_engine.ReminderEngine()
        payload = _reminder()

        async def inactive():
            return []

        async def mark(*args, **kwargs):
            raise AssertionError("offline reminders must not be marked failed")

        monkeypatch.setattr(reminder_engine.connection_registry, "all_active", inactive)
        monkeypatch.setattr(reminder_engine.cal, "mark_reminder", mark)
        engine._index[payload["id"]] = {
            **payload,
            "remind_at": datetime.now(reminder_engine.TZ) - timedelta(seconds=1),
            "expires_at": datetime.now(reminder_engine.TZ) + timedelta(minutes=5),
            "retries": 0,
            "last_sent": 0.0,
            "last_attempt": 0.0,
            "acked": False,
        }

        await engine._tick()
        assert payload["id"] in engine._index
        assert engine._index[payload["id"]]["retries"] == 0

    asyncio.run(run())

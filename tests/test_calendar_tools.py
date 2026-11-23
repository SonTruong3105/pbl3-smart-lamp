import asyncio

from app.core.providers.tools import calendar as calendar_tools
from app.core.providers.tools.unified.register import Action


class _Connection:
    _pending_calendar = None


def test_update_calendar_event_validates_merged_payload_and_stages_normalized_changes(monkeypatch):
    conn = _Connection()
    current = {
        "id": "event-1",
        "title": "Planning",
        "date": "2026-11-20",
        "start_time": "09:00",
        "end_time": "10:00",
        "note": "",
        "remind_minutes": 0,
        "revision": 3,
        "device_id": None,
    }

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(calendar_tools, "_conn", lambda: (conn, None))
    monkeypatch.setattr(calendar_tools, "AsyncSessionLocal", _Session)

    async def get_event(_db, _event_id, device_id=None):
        return current

    monkeypatch.setattr(calendar_tools.cal, "get_event", get_event)

    async def run():
        response = await calendar_tools.update_calendar_event("event-1", title="  New title  ")
        assert response.action == Action.RESPONSE
        assert conn._pending_calendar["payload"] == {"title": "New title"}
        assert conn._pending_calendar["revision"] == current["revision"]
        assert conn._pending_calendar["expires_at"] > calendar_tools.time.monotonic()
        assert conn._pending_calendar["token"]
        assert "15 phút" in response.response

    asyncio.run(run())


def test_update_calendar_event_rejects_invalid_merged_payload(monkeypatch):
    conn = _Connection()
    current = {
        "id": "event-1",
        "title": "Planning",
        "date": "2026-11-20",
        "start_time": "09:00",
        "end_time": "10:00",
        "note": "",
        "remind_minutes": 0,
        "revision": 3,
        "device_id": None,
    }

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(calendar_tools, "_conn", lambda: (conn, None))
    monkeypatch.setattr(calendar_tools, "AsyncSessionLocal", _Session)

    async def get_event(_db, _event_id, device_id=None):
        return current

    monkeypatch.setattr(calendar_tools.cal, "get_event", get_event)

    async def run():
        response = await calendar_tools.update_calendar_event("event-1", start_time="10:30")
        assert response.action == Action.ERROR
        assert "kết thúc" in response.result
        assert conn._pending_calendar is None

    asyncio.run(run())


def test_execute_pending_requires_token_and_consumes_before_write(monkeypatch):
    conn = _Connection()
    conn._pending_calendar = {
        "action": "create",
        "payload": {"title": "Test"},
        "summary": "Thêm lịch Test",
        "token": "secret-token",
        "expires_at": calendar_tools.time.monotonic() + 60,
    }
    writes = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def create_event(_db, payload, device_id=None):
        writes.append(payload)
        return {"title": "Test", "date": "2026-11-20", "start_time": "09:00", "end_time": "10:00"}

    monkeypatch.setattr(calendar_tools, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(calendar_tools.cal, "create_event", create_event)

    async def run():
        invalid = await calendar_tools.execute_pending(conn, "wrong-token")
        assert "không đúng" in invalid
        assert conn._pending_calendar is not None
        response = await calendar_tools.execute_pending(conn, "secret-token")
        assert response.startswith("Đã thêm lịch Test")
        assert writes == [{"title": "Test"}]
        assert conn._pending_calendar is None
        replay = await calendar_tools.execute_pending(conn, "secret-token")
        assert "Không có đề xuất" in replay

    asyncio.run(run())


def test_execute_pending_expired_proposal_is_cleared():
    conn = _Connection()
    conn._pending_calendar = {
        "action": "create", "token": "secret-token",
        "expires_at": calendar_tools.time.monotonic() - 1,
    }

    async def run():
        response = await calendar_tools.execute_pending(conn, "secret-token")
        assert "hết hạn" in response
        assert conn._pending_calendar is None

    asyncio.run(run())


def test_execute_pending_revision_conflict_consumes_proposal(monkeypatch):
    conn = _Connection()
    conn._pending_calendar = {
        "action": "update", "event_id": "event-1", "revision": 2,
        "payload": {"title": "New"}, "token": "secret-token",
        "expires_at": calendar_tools.time.monotonic() + 60,
    }

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def update_event(*_args, **_kwargs):
        raise calendar_tools.cal.CalendarConflict("Lịch đã thay đổi.")

    monkeypatch.setattr(calendar_tools, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(calendar_tools.cal, "update_event", update_event)

    async def run():
        response = await calendar_tools.execute_pending(conn, "secret-token")
        assert "Lịch đã thay đổi" in response
        assert conn._pending_calendar is None

    asyncio.run(run())

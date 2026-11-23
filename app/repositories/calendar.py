"""Async calendar repository — SQLite via SQLAlchemy with event listener support."""
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional, Callable, List
import json
from uuid import uuid4

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models import CalendarEvent, CalendarReminder

TZ = timezone(timedelta(hours=7))
FIELDS = ("title", "date", "start_time", "end_time", "note", "remind_minutes")

_change_listeners: List[Callable[[], None]] = []


def _now_tz() -> datetime:
    return datetime.now(TZ)


def add_change_listener(listener: Callable[[], None]) -> None:
    """Đăng ký listener khi calendar thay đổi (tránh circular import)."""
    if listener not in _change_listeners:
        _change_listeners.append(listener)


def remove_change_listener(listener: Callable[[], None]) -> None:
    if listener in _change_listeners:
        _change_listeners.remove(listener)


def _notify_change() -> None:
    for listener in _change_listeners:
        try:
            listener()
        except Exception as e:
            logger.debug(f"Calendar listener error: {e}")


class CalendarError(ValueError): pass
class CalendarConflict(CalendarError): pass


def _v_date(s):
    if not isinstance(s, str) or len(s) != 10:
        raise CalendarError("Ngày phải có dạng YYYY-MM-DD.")
    try: return date_cls.fromisoformat(s)
    except ValueError: raise CalendarError("Ngày không hợp lệ.")


def _v_time(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        raise CalendarError("Giờ phải có dạng HH:MM.")
    try:
        h, m = int(s[:2]), int(s[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
    except (ValueError, IndexError):
        raise CalendarError("Giờ không hợp lệ.")
    return s


def validate_payload(payload: dict, current: dict = None) -> dict:
    if not isinstance(payload, dict) or set(payload) - set(FIELDS):
        raise CalendarError("Dữ liệu lịch chứa trường không hợp lệ.")
    values = dict(current) if current else {"note": "", "remind_minutes": 0}
    values.update({k: v for k, v in payload.items() if k in FIELDS})
    if values.keys() != set(FIELDS):
        raise CalendarError("Thiếu tiêu đề, ngày hoặc giờ.")
    t = values["title"]
    if not isinstance(t, str) or not t.strip() or len(t) > 120 or "\x00" in t:
        raise CalendarError("Tiêu đề 1-120 ký tự.")
    values["title"] = t.strip()
    _v_date(values["date"]); _v_time(values["start_time"]); _v_time(values["end_time"])
    if values["end_time"] <= values["start_time"]:
        raise CalendarError("Giờ kết thúc phải sau giờ bắt đầu.")
    n = values["note"]
    if not isinstance(n, str) or len(n) > 2000 or "\x00" in n:
        raise CalendarError("Ghi chú tối đa 2000 ký tự.")
    values["note"] = n.strip()
    rm = values["remind_minutes"]
    if type(rm) is not int or not (0 <= rm <= 1440):
        raise CalendarError("remind_minutes phải 0-1440.")
    return values


def _to_dict(ev) -> dict:
    return {"id": ev.id, "title": ev.title, "date": ev.date,
            "start_time": ev.start_time, "end_time": ev.end_time,
            "note": ev.note or "", "remind_minutes": ev.remind_minutes or 0,
            "revision": ev.revision, "device_id": ev.device_id}


async def _scope(q, device_id):
    if device_id is not None:
        return q.where(CalendarEvent.device_id == device_id)
    return q.where(CalendarEvent.device_id.is_(None))


async def _get_or_none(db, event_id, device_id=None):
    q = select(CalendarEvent).where(CalendarEvent.id == event_id)
    q = await _scope(q, device_id)
    return (await db.execute(q)).scalar_one_or_none()


async def _check_overlap(db, values, exclude_id=None, device_id=None):
    q = select(CalendarEvent).where(and_(
        CalendarEvent.date == values["date"],
        CalendarEvent.start_time < values["end_time"],
        CalendarEvent.end_time > values["start_time"],
    ))
    q = await _scope(q, device_id)
    if exclude_id: q = q.where(CalendarEvent.id != exclude_id)
    if (await db.execute(q)).first():
        raise CalendarConflict("Khoảng giờ trùng với lịch khác.")


async def create_event(db, payload, device_id=None):
    values = validate_payload(payload)
    await _check_overlap(db, values, device_id=device_id)
    ev = CalendarEvent(id=str(uuid4()), device_id=device_id, revision=1, **values)
    db.add(ev); await db.commit(); await db.refresh(ev)
    _notify_change()
    return _to_dict(ev)


async def update_event(db, event_id, payload, expected_revision, device_id=None):
    ev = await _get_or_none(db, event_id, device_id)
    if not ev: raise CalendarConflict("Lịch không tồn tại.")
    if ev.revision != expected_revision: raise CalendarConflict("Lịch đã thay đổi.")
    values = validate_payload(payload, _to_dict(ev))
    await _check_overlap(db, values, exclude_id=event_id, device_id=device_id)
    for k, v in values.items(): setattr(ev, k, v)
    ev.revision += 1; ev.updated_at = _now_tz()
    await db.execute(CalendarReminder.__table__.update()
                     .where(CalendarReminder.event_id == event_id).values(active=0))
    await db.commit(); await db.refresh(ev)
    _notify_change()
    return _to_dict(ev)


async def delete_event(db, event_id, expected_revision, device_id=None):
    ev = await _get_or_none(db, event_id, device_id)
    if not ev: raise CalendarConflict("Lịch không tồn tại.")
    if ev.revision != expected_revision: raise CalendarConflict("Lịch đã thay đổi.")
    await db.execute(CalendarReminder.__table__.update()
                     .where(CalendarReminder.event_id == event_id).values(active=0))
    await db.delete(ev); await db.commit()
    _notify_change()


async def list_events(db, start_date, end_date, device_id=None):
    _v_date(start_date); _v_date(end_date)
    q = select(CalendarEvent).where(and_(
        CalendarEvent.date >= start_date, CalendarEvent.date <= end_date))
    q = await _scope(q, device_id)
    q = q.order_by(CalendarEvent.date, CalendarEvent.start_time)
    return [_to_dict(r) for r in (await db.execute(q)).scalars().all()]


async def get_event(db, event_id, device_id=None):
    ev = await _get_or_none(db, event_id, device_id)
    return _to_dict(ev) if ev else None


async def due_reminders(db, now, lookahead_hours: int = 24) -> list:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CalendarError("Thời điểm phải có timezone.")
    now = now.astimezone(TZ)
    today = now.date()
    tomorrow = date_cls.fromordinal(min(today.toordinal() + max(1, lookahead_hours // 24), date_cls.max.toordinal()))
    q = (select(CalendarEvent, CalendarReminder)
         .outerjoin(CalendarReminder, and_(
             CalendarReminder.event_id == CalendarEvent.id,
             CalendarReminder.revision == CalendarEvent.revision))
         .where(and_(
             CalendarEvent.date >= today.isoformat(),
             CalendarEvent.date <= tomorrow.isoformat(),
         )))
    due = []
    added = False
    for ev, rem in (await db.execute(q)).all():
        if rem and rem.status in ("played", "failed", "cancelled"):
            continue
        start = datetime.fromisoformat(f'{ev.date}T{ev.start_time}').replace(tzinfo=TZ)
        end = datetime.fromisoformat(f'{ev.date}T{ev.end_time}').replace(tzinfo=TZ)
        if now >= end or start - now > timedelta(minutes=ev.remind_minutes or 0):
            continue
        rid = f"{ev.id}:{ev.revision}"
        payload = {"id": rid, "event": _to_dict(ev),
                   "text": f"Nhắc lịch: {ev.title}, {ev.start_time} ngày {ev.date}.",
                   "expires_at": end.isoformat()}
        if rem is None:
            existing = (await db.execute(
                select(CalendarReminder).where(CalendarReminder.id == rid)
            )).scalar_one_or_none()
            if existing is None:
                db.add(CalendarReminder(id=rid, event_id=ev.id, revision=ev.revision,
                                         payload=json.dumps(payload, ensure_ascii=False),
                                         status="pending", active=1))
                added = True
        due.append(payload)
    if added:
        await db.commit()
    return due


async def mark_reminder(db, reminder_id, status):
    if status not in ("played", "failed", "cancelled"):
        raise CalendarError("Trạng thái không hợp lệ.")
    rem = (await db.execute(select(CalendarReminder)
            .where(CalendarReminder.id == reminder_id))).scalar_one_or_none()
    if not rem: return
    if rem.status != "played":
        rem.status = status
        rem.updated_at = _now_tz()
        await db.commit()
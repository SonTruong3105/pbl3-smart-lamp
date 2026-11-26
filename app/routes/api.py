"""API routes — audio, calendar."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models import Message, Session
from app.repositories import calendar as cal

router = APIRouter()
AUDIO_DIR = Path("data").resolve()
ROLE_ALIASES = {"user": "user", "bot": "bot", "assistant": "bot"}


# ═══ AUDIO API ═══
@router.get("/api/audio/{message_id}")
async def get_audio(message_id: int, role: str = "user",
                    x_device_id: str = Header(default="", alias="X-Device-Id")):
    folder = ROLE_ALIASES.get(role)
    if not folder:
        raise HTTPException(400, f"Invalid role '{role}'")
    if not x_device_id:
        raise HTTPException(401, "Missing X-Device-Id header")

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Session.device_id)
            .join(Message, Message.session_id == Session.id)
            .where(Message.id == message_id))
        owner = r.scalar_one_or_none()
    if owner is None:
        raise HTTPException(404, "Audio not found")
    if owner != x_device_id:
        raise HTTPException(403, "Forbidden")

    for ext in (["mp3", "wav"] if folder == "bot" else ["wav", "mp3"]):
        fp = AUDIO_DIR / folder / f"{message_id}.{ext}"
        if fp.exists():
            return FileResponse(str(fp),
                media_type="audio/mpeg" if ext == "mp3" else "audio/wav")
    raise HTTPException(404, "Audio not found")


# ═══ CALENDAR API ═══
def _to_frontend(ev: dict) -> dict:
    return {
        "id": ev["id"],
        "title": ev["title"],
        "date": ev["date"],
        "start": ev["start_time"],
        "end": ev["end_time"],
        "note": ev.get("note", ""),
        "remind_minutes": ev.get("remind_minutes", 0),
        "revision": ev["revision"],
    }


def _from_frontend(data: dict) -> dict:
    return {
        "title": data.get("title", ""),
        "date": data.get("date", ""),
        "start_time": data.get("start", data.get("start_time", "")),
        "end_time": data.get("end", data.get("end_time", "")),
        "note": data.get("note", ""),
        "remind_minutes": data.get("remind_minutes", 0),
    }


@router.get("/api/events")
async def get_events(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    week: Optional[str] = Query(default=None),
    days: int = Query(default=7),
    db: AsyncSession = Depends(get_db),
):
    try:
        if start_date or end_date:
            today = date.today()
            start = date.fromisoformat(start_date) if start_date else today
            end = date.fromisoformat(end_date) if end_date else (start + timedelta(days=30))
        elif week:
            if days < 1 or days > 42:
                raise cal.CalendarError("Khoảng thời gian không hợp lệ.")
            start = date.fromisoformat(week)
            end = start + timedelta(days=days - 1)
        else:
            start = date.today()
            end = start + timedelta(days=30)

        if end < start:
            raise cal.CalendarError("end_date phải lớn hơn hoặc bằng start_date.")

        events = await cal.list_events(
            db, start.isoformat(), end.isoformat(), device_id=None,
        )
        return {"events": [_to_frontend(e) for e in events]}
    except ValueError:
        raise HTTPException(400, detail="Định dạng ngày không hợp lệ (cần YYYY-MM-DD).")
    except cal.CalendarError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/api/events")
async def create_event(data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        payload = _from_frontend(data)
        ev = await cal.create_event(db, payload, device_id=None)
        return _to_frontend(ev)
    except cal.CalendarConflict as e:
        raise HTTPException(409, detail=str(e))
    except cal.CalendarError as e:
        raise HTTPException(400, detail=str(e))


@router.put("/api/events/{event_id}")
async def update_event(event_id: str, data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        revision = data.pop("revision", 1)
        payload = _from_frontend(data)
        ev = await cal.update_event(db, event_id, payload, revision, device_id=None)
        return _to_frontend(ev)
    except cal.CalendarConflict as e:
        raise HTTPException(409, detail=str(e))
    except cal.CalendarError as e:
        raise HTTPException(400, detail=str(e))


@router.delete("/api/events/{event_id}")
async def delete_event(event_id: str, data: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        revision = data.get("revision", 1)
        await cal.delete_event(db, event_id, revision, device_id=None)
        return {"status": "ok"}
    except cal.CalendarConflict as e:
        raise HTTPException(409, detail=str(e))
    except cal.CalendarError as e:
        raise HTTPException(400, detail=str(e))


@router.get("/api/agenda")
async def get_agenda(db: AsyncSession = Depends(get_db)):
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    events = await cal.list_events(db, today, upcoming_date, device_id=None)
    events_fe = [_to_frontend(e) for e in events]
    return {
        "today": [e for e in events_fe if e["date"] == today],
        "upcoming": events_fe,
    }

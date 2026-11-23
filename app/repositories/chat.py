"""CRUD operations for Devices, Sessions, Messages (Repository)."""
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.models import Device, Session, Message

AUDIO_DIR = Path("data")


def _session_activity_time(s: Session) -> datetime:
    """Lấy thời điểm hoạt động gần nhất (ưu tiên last_activity_at, fallback started_at)."""
    return getattr(s, "last_activity_at", None) or s.started_at


def _mark_session_activity(s: Session, ts: datetime) -> None:
    """Cập nhật last_activity_at nếu Session model có cột này."""
    if hasattr(s, "last_activity_at"):
        setattr(s, "last_activity_at", ts)


# ============ DEVICE ============

async def get_or_create_device(db: AsyncSession, device_id: str, dtype: str = "browser"):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    now = datetime.utcnow()
    if not device:
        device = Device(id=device_id, name=device_id, type=dtype, first_seen=now, last_seen=now)
        db.add(device)
        await db.commit()
        await db.refresh(device)
    else:
        device.last_seen = now
        await db.commit()
    return device


async def list_devices(db: AsyncSession):
    result = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    return result.scalars().all()


# ============ SESSION ============

async def create_session(db: AsyncSession, device_id: str):
    now = datetime.utcnow()
    kwargs = {"device_id": device_id, "started_at": now}
    if hasattr(Session, "last_activity_at"):
        kwargs["last_activity_at"] = now
    s = Session(**kwargs)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def get_session(db: AsyncSession, session_id: int):
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def touch_session(db: AsyncSession, session_id: int) -> None:
    """Cập nhật thời điểm hoạt động gần nhất của session."""
    if not hasattr(Session, "last_activity_at"):
        return
    s = await get_session(db, session_id)
    if s:
        _mark_session_activity(s, datetime.utcnow())
        await db.commit()


async def resume_or_create_session(
    db: AsyncSession,
    device_id: str,
    client_session_id: int | None = None,
    *,
    force_new: bool = False,
) -> tuple[Session, bool]:
    """
    Nối tiếp session đang mở hoặc nằm trong cửa sổ resume; nếu hết hạn hoặc force_new thì tạo mới.
    Trả về (session, is_new).
    """
    now = datetime.utcnow()
    idle_sec = max(30, int(config.session_max_idle_duration))
    resume_sec = max(0, int(config.session_resume_window_minutes)) * 60

    idle_cutoff = now - timedelta(seconds=idle_sec)
    resume_cutoff = now - timedelta(seconds=resume_sec)
    changed = False

    if not force_new and client_session_id is not None:
        s = await get_session(db, client_session_id)
        if s and s.device_id == device_id:
            if s.ended_at is None:
                if _session_activity_time(s) >= idle_cutoff:
                    _mark_session_activity(s, now)
                    await db.commit()
                    await db.refresh(s)
                    return s, False
                s.ended_at = now
                changed = True
            elif s.ended_at >= resume_cutoff:
                s.ended_at = None
                _mark_session_activity(s, now)
                await db.commit()
                await db.refresh(s)
                return s, False

    if not force_new:
        result = await db.execute(
            select(Session)
            .where(Session.device_id == device_id)
            .order_by(Session.id.desc())
            .limit(5)
        )
        candidates = result.scalars().all()
        for s in candidates:
            if s.ended_at is None:
                if _session_activity_time(s) >= idle_cutoff:
                    _mark_session_activity(s, now)
                    await db.commit()
                    await db.refresh(s)
                    return s, False
                s.ended_at = now
                changed = True
            elif s.ended_at >= resume_cutoff:
                s.ended_at = None
                _mark_session_activity(s, now)
                await db.commit()
                await db.refresh(s)
                return s, False

    if changed:
        await db.commit()

    s = await create_session(db, device_id)
    return s, True


async def cleanup_stale_sessions(
    db: AsyncSession,
    max_idle_hours: int | None = None,
    idle_seconds: int | None = None,
) -> int:
    """Đóng các session còn mở nhưng đã vượt quá thời gian nhàn rỗi."""
    now = datetime.utcnow()
    if idle_seconds is not None:
        cutoff = now - timedelta(seconds=max(30, int(idle_seconds)))
    else:
        hours = max_idle_hours if max_idle_hours is not None else max(
            1, (int(config.session_max_idle_duration) + 3599) // 3600
        )
        cutoff = now - timedelta(hours=max(1, int(hours)))

    result = await db.execute(
        select(Session).where(Session.ended_at.is_(None))
    )
    open_sessions = result.scalars().all()

    closed = 0
    for s in open_sessions:
        if _session_activity_time(s) < cutoff:
            s.ended_at = now
            closed += 1

    if closed:
        await db.commit()
    return closed


async def get_recent_sessions(db: AsyncSession, limit: int = 20, device_id: str | None = None):
    query = select(Session).order_by(Session.id.desc()).limit(limit)
    if device_id:
        query = (
            select(Session)
            .where(Session.device_id == device_id)
            .order_by(Session.id.desc())
            .limit(limit)
        )
    result = await db.execute(query)
    return result.scalars().all()


async def close_session(db: AsyncSession, session_id: int):
    s = await get_session(db, session_id)
    if s and s.ended_at is None:
        now = datetime.utcnow()
        s.ended_at = now
        _mark_session_activity(s, now)
        await db.commit()


async def delete_session(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id)
    )
    messages = result.scalars().all()

    for msg in messages:
        if msg.audio_path:
            p = Path(msg.audio_path)
            if p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    logger.warning(f"⚠️ Không xóa được {p}: {e}")

    for msg in messages:
        await db.delete(msg)

    s = await get_session(db, session_id)
    if s:
        await db.delete(s)
    await db.commit()


async def cleanup_old_sessions(db: AsyncSession, days: int | None = None) -> int:
    keep_days = int(config.session_cleanup_days) if days is None else int(days)
    cutoff = datetime.utcnow() - timedelta(days=max(1, keep_days))
    result = await db.execute(select(Session).where(Session.started_at < cutoff))
    sessions = result.scalars().all()
    for s in sessions:
        await delete_session(db, s.id)
    return len(sessions)


# ============ MESSAGE ============

async def save_message(
    db: AsyncSession,
    session_id: int,
    role: str,
    content: str,
    turn_id: str | None = None,
    audio_bytes: bytes | None = None,
    audio_ext: str = "wav",
):
    now = datetime.utcnow()
    msg = Message(
        session_id=session_id,
        role=role,
        content=content,
        turn_id=turn_id,
        created_at=now,
    )
    db.add(msg)

    s = await get_session(db, session_id)
    if s:
        s.message_count = (s.message_count or 0) + 1
        _mark_session_activity(s, now)

    await db.flush()

    if audio_bytes and len(audio_bytes) > 0:
        sub = "user" if role == "user" else "bot"
        audio_dir = AUDIO_DIR / sub
        audio_dir.mkdir(parents=True, exist_ok=True)
        file_path = audio_dir / f"{msg.id}.{audio_ext}"

        try:
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
            msg.audio_path = str(file_path).replace("\\", "/")
        except Exception as e:
            logger.error(f"⚠️ Lỗi lưu audio: {e}")

    await db.commit()
    await db.refresh(msg)
    return msg, Path(msg.audio_path) if msg.audio_path else None


async def get_session_history(
    db: AsyncSession,
    session_id: int,
    limit: int | None = None,
):
    query = select(Message).where(Message.session_id == session_id)
    if limit is None:
        result = await db.execute(query.order_by(Message.id))
        messages = result.scalars().all()
    else:
        result = await db.execute(
            query.order_by(Message.id.desc()).limit(max(1, limit))
        )
        messages = list(reversed(result.scalars().all()))
    while messages and messages[0].role == "tool":
        messages.pop(0)
    return [{"role": m.role, "content": m.content} for m in messages]


async def get_session_messages(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    )
    return result.scalars().all()


async def get_stats(db: AsyncSession):
    d = await db.execute(select(func.count(Device.id)))
    s = await db.execute(select(func.count(Session.id)))
    m = await db.execute(select(func.count(Message.id)))
    return {
        "devices": d.scalar() or 0,
        "sessions": s.scalar() or 0,
        "messages": m.scalar() or 0,
    }
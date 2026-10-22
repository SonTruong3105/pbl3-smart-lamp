"""CRUD operations."""
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.models import Device, Session, Message


AUDIO_DIR = Path("data/audio")


# ============ DEVICE ============

async def get_or_create_device(db: AsyncSession, device_id: str, dtype: str = "browser"):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        device = Device(id=device_id, name=device_id, type=dtype)
        db.add(device)
        await db.commit()
        await db.refresh(device)
    else:
        device.last_seen = datetime.utcnow()
        await db.commit()
    return device


async def list_devices(db: AsyncSession):
    result = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    return result.scalars().all()


# ============ SESSION ============

async def create_session(db: AsyncSession, device_id: str):
    s = Session(device_id=device_id)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def get_session(db: AsyncSession, session_id: int):
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def resume_or_create_session(
    db: AsyncSession, device_id: str, client_session_id: int | None,
) -> tuple:
    """Trả về (session, is_new)."""
    resume_sec = config.session_resume_window_minutes * 60

    if client_session_id is not None:
        s = await get_session(db, client_session_id)
        if s and s.device_id == device_id:
            if s.ended_at is None:
                return s, False
            delta = datetime.utcnow() - s.ended_at
            if delta.total_seconds() < resume_sec:
                s.ended_at = None
                await db.commit()
                await db.refresh(s)
                return s, False

    s = await create_session(db, device_id)
    return s, True


async def get_recent_sessions(db: AsyncSession, limit: int = 20, device_id: str = None):
    query = select(Session).order_by(Session.id.desc()).limit(limit)
    if device_id:
        query = select(Session).where(Session.device_id == device_id) \
                               .order_by(Session.id.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def close_session(db: AsyncSession, session_id: int):
    s = await get_session(db, session_id)
    if s and s.ended_at is None:
        s.ended_at = datetime.utcnow()
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


async def cleanup_old_sessions(db: AsyncSession, days: int = 7) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(select(Session).where(Session.started_at < cutoff))
    sessions = result.scalars().all()
    for s in sessions:
        await delete_session(db, s.id)
    return len(sessions)


# ============ MESSAGE ============

async def save_message(
    db: AsyncSession, session_id: int, role: str, content: str,
    audio_bytes: bytes = None, audio_ext: str = "wav",
):
    msg = Message(session_id=session_id, role=role, content=content)
    db.add(msg)

    s = await get_session(db, session_id)
    if s:
        s.message_count = (s.message_count or 0) + 1

    await db.commit()
    await db.refresh(msg)

    if audio_bytes and len(audio_bytes) > 0:
        sub = "user" if role == "user" else "bot"
        audio_dir = AUDIO_DIR / sub
        audio_dir.mkdir(parents=True, exist_ok=True)
        file_path = audio_dir / f"{msg.id}.{audio_ext}"

        try:
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
            msg.audio_path = str(file_path).replace("\\", "/")
            await db.commit()
            return msg, file_path
        except Exception as e:
            logger.error(f"⚠️ Lỗi lưu audio: {e}")

    return msg, None


async def get_session_history(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    )
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]


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
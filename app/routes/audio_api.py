"""API phục vụ audio — yêu cầu X-Device-Id khớp owner."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Message, Session

router = APIRouter()
AUDIO_DIR = Path("data").resolve()
ROLE_ALIASES = {"user": "user", "bot": "bot", "assistant": "bot"}


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
"""API phục vụ file audio."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
AUDIO_DIR = Path("data").resolve()

ROLE_ALIASES = {
    "user": "user",
    "bot": "bot",
    "assistant": "bot",
}


@router.get("/api/audio/{message_id}")
async def get_audio(message_id: int, role: str = "user"):
    folder = ROLE_ALIASES.get(role)
    if not folder:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {list(ROLE_ALIASES.keys())}",
        )

    exts = ["mp3", "wav"] if folder == "bot" else ["wav", "mp3"]

    for ext in exts:
        file_path = AUDIO_DIR / folder / f"{message_id}.{ext}"
        if file_path.exists():
            media_type = "audio/mpeg" if ext == "mp3" else "audio/wav"
            return FileResponse(
                path=str(file_path),
                media_type=media_type,
                filename=f"{folder}_{message_id}.{ext}",
            )

    raise HTTPException(status_code=404, detail="Audio not found")
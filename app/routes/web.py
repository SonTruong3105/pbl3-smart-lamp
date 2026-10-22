from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.logger import list_session_logs, read_session_log
from app.services import chat as chat_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def root():
    return RedirectResponse(url="/chat")


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    device_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stats = await chat_service.get_stats(db)
    devices = await chat_service.list_devices(db)
    sessions = await chat_service.get_recent_sessions(db, limit=30, device_id=device_id)

    sessions_data = []
    for s in sessions:
        msgs = await chat_service.get_session_messages(db, s.id)
        sessions_data.append({
            "id": s.id,
            "device_id": s.device_id,
            "started_at": s.started_at.strftime("%H:%M %d/%m/%Y") if s.started_at else "",
            "ended_at": s.ended_at.strftime("%H:%M %d/%m/%Y") if s.ended_at else "",
            "message_count": s.message_count,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "audio_path": m.audio_path}
                for m in msgs
            ],
        })

    return templates.TemplateResponse(
        request=request, name="admin.html",
        context={
            "stats": stats,
            "sessions": sessions_data,
            "devices": devices,
            "current_device": device_id,
        },
    )


@router.get("/logs")
async def logs_redirect():
    return RedirectResponse(url="/admin/logs")


@router.get("/admin/log")
async def admin_log_redirect():
    return RedirectResponse(url="/admin/logs")


@router.get("/admin/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    logs = list_session_logs()
    return templates.TemplateResponse(
        request=request, name="logs.html", context={"logs": logs},
    )


@router.get("/admin/logs/{session_id}", response_class=PlainTextResponse)
async def view_session_log(session_id: str, tail: int = 500):
    content = read_session_log(session_id, tail=tail)
    if not content:
        return PlainTextResponse("Không tìm thấy log", status_code=404)
    return PlainTextResponse(content)
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.logger import list_session_logs, read_session_log

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/index", response_class=HTMLResponse)
async def index_alias(request: Request):
    return await index_page(request)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return await index_page(request)


@router.get("/api/logs")
async def api_logs():
    return {"logs": list_session_logs()}


@router.get("/api/logs/{session_id}")
async def api_log_content(session_id: str, tail: int = 500):
    # Session IDs are autoincremented integers; reject anything that could
    # escape the session-log namespace before constructing a filesystem path.
    if not session_id.isascii() or not session_id.isdecimal():
        return {"error": "Không tìm thấy log"}
    tail = max(1, min(tail, 2000))
    content = read_session_log(session_id, tail=tail)
    if not content:
        return {"error": "Không tìm thấy log"}
    return {"content": content}
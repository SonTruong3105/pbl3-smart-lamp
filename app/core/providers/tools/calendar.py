"""Calendar tools — human-in-the-loop confirmation (port từ AI Chatbot)."""
from datetime import date, datetime, timedelta
import secrets
import time

from loguru import logger

from app.core.providers.tools.unified.register import (
    Action, ActionResponse, register_function)
from app.core.providers.tools.context import get_connection
from app.database import AsyncSessionLocal
from app.repositories import calendar as cal

_WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
_PENDING_SECONDS = 15 * 60


def _stage(conn, proposal: dict, summary: str) -> ActionResponse:
    """Stage a single-use proposal for this connection's next explicit confirmation."""
    proposal = {
        **proposal,
        "token": secrets.token_urlsafe(32),
        "expires_at": time.monotonic() + _PENDING_SECONDS,
    }
    proposal["summary"] = summary
    conn._pending_calendar = proposal
    text = f"Mình sẽ {summary.lower()}. Bạn xác nhận hay hủy trong 15 phút?"
    return ActionResponse(Action.RESPONSE, result=text, response=text)


def _conn():
    c = get_connection()
    if c is None:
        return None, ActionResponse(Action.ERROR, result="Không có connection.")
    return c, None


def _fmt_time_natural(hhmm: str) -> str:
    """Chuyển '07:30' -> '7 giờ 30', '09:00' -> '9 giờ' để TTS đọc tự nhiên."""
    try:
        h, m = map(int, hhmm.split(":")[:2])
        return f"{h} giờ {m:02d}" if m else f"{h} giờ"
    except Exception:
        return hhmm


def _fmt_date_natural(date_str: str) -> str:
    """Chuyển '2026-11-17' -> 'hôm nay', 'ngày mai' hoặc 'ngày 17 tháng 11'."""
    try:
        target = date.fromisoformat(date_str)
        today = date.today()
        diff = (target - today).days
        if diff == 0:
            return "hôm nay"
        if diff == 1:
            return "ngày mai"
        if diff == -1:
            return "hôm qua"
        return f"ngày {target.day} tháng {target.month}"
    except Exception:
        return date_str


@register_function(
    name="list_calendar",
    description="Đọc lịch trong khoảng ngày (YYYY-MM-DD, bao gồm 2 đầu).",
    parameters={
        "start_date": {"type": "string", "required": True},
        "end_date":   {"type": "string", "required": True},
    },
)
async def list_calendar(start_date: str, end_date: str) -> ActionResponse:
    conn, err = _conn()
    if err:
        return err
    try:
        async with AsyncSessionLocal() as db:
            events = await cal.list_events(db, start_date, end_date, device_id=None)
    except cal.CalendarError as e:
        return ActionResponse(Action.ERROR, result=str(e))

    now = datetime.now()
    weekday = _WEEKDAYS_VI[now.weekday()]
    now_ctx = f"Hiện tại là {now.strftime('%H:%M')} {weekday}, ngày {now.strftime('%d/%m/%Y')}."

    if not events:
        range_desc = _fmt_date_natural(start_date) if start_date == end_date else f"từ {_fmt_date_natural(start_date)} đến {_fmt_date_natural(end_date)}"
        raw = f"{now_ctx} Người dùng không có lịch trình nào vào {range_desc}. Hãy báo lại ngắn gọn, tự nhiên."
        return ActionResponse(Action.REQLLM, result=raw)

    lines = [
        f"{now_ctx} Dưới đây là danh sách lịch trình của người dùng. "
        "Hãy tóm tắt lại thành 1-2 câu nói tiếng Việt tự nhiên, thân thiện để đọc thành tiếng "
        "(chuyển giờ sang dạng 'X giờ Y', phân biệt rõ sự kiện đã qua hay sắp diễn ra, không dùng ký tự gạch đầu dòng hay mã ngày ISO):"
    ]
    for ev in events:
        d_label = _fmt_date_natural(ev["date"])
        t_start = _fmt_time_natural(ev["start_time"])
        t_end = _fmt_time_natural(ev["end_time"])
        note_str = f" (ghi chú: {ev['note']})" if ev.get("note") else ""
        lines.append(f"- {d_label}, từ {t_start} đến {t_end}: {ev['title']}{note_str}")

    return ActionResponse(Action.REQLLM, result="\n".join(lines))


@register_function(
    name="add_calendar_event",
    description="ĐỀ XUẤT thêm lịch. Phải xác nhận mới lưu (không lưu ngay).",
    parameters={
        "title":          {"type": "string",  "required": True},
        "date":           {"type": "string",  "description": "YYYY-MM-DD", "required": True},
        "start_time":     {"type": "string",  "description": "HH:MM", "required": True},
        "end_time":       {"type": "string",  "description": "HH:MM", "required": True},
        "note":           {"type": "string"},
        "remind_minutes": {"type": "integer"},
    },
)
async def add_calendar_event(title, date, start_time, end_time,
                             note="", remind_minutes=0) -> ActionResponse:
    conn, err = _conn()
    if err:
        return err
    payload = dict(title=title, date=date, start_time=start_time,
                   end_time=end_time, note=note, remind_minutes=remind_minutes)
    try:
        payload = cal.validate_payload(payload)
    except cal.CalendarError as e:
        return ActionResponse(Action.ERROR, result=str(e))

    title, date = payload["title"], payload["date"]
    start_time, end_time = payload["start_time"], payload["end_time"]
    d_nat = _fmt_date_natural(date)
    s_nat = _fmt_time_natural(start_time)
    e_nat = _fmt_time_natural(end_time)

    summary = f"Thêm lịch {title} vào {d_nat}, từ {s_nat} đến {e_nat}"
    return _stage(conn, {"action": "create", "payload": payload}, summary)


@register_function(
    name="update_calendar_event",
    description="ĐỀ XUẤT sửa lịch đã có.",
    parameters={
        "event_id":       {"type": "string",  "required": True},
        "title":          {"type": "string"},
        "date":           {"type": "string"},
        "start_time":     {"type": "string"},
        "end_time":       {"type": "string"},
        "note":           {"type": "string"},
        "remind_minutes": {"type": "integer"},
    },
)
async def update_calendar_event(event_id, title=None, date=None,
                                start_time=None, end_time=None,
                                note=None, remind_minutes=None) -> ActionResponse:
    conn, err = _conn()
    if err:
        return err
    async with AsyncSessionLocal() as db:
        cur = await cal.get_event(db, event_id, device_id=None)
    if not cur:
        return ActionResponse(Action.ERROR, result="Không tìm thấy lịch.")
    changes = {k: v for k, v in dict(title=title, date=date, start_time=start_time,
               end_time=end_time, note=note, remind_minutes=remind_minutes).items()
               if v is not None}
    if not changes:
        return ActionResponse(Action.ERROR, result="Không có thay đổi.")
    try:
        values = {key: cur[key] for key in cal.FIELDS}
        validated = cal.validate_payload({**values, **changes}, values)
        # Persist normalized values too (notably trimmed title/note), not raw tool input.
        changes = {key: validated[key] for key in changes}
    except cal.CalendarError as e:
        return ActionResponse(Action.ERROR, result=str(e))

    merged = {**cur, **changes}
    d_nat = _fmt_date_natural(merged["date"])
    s_nat = _fmt_time_natural(merged["start_time"])
    e_nat = _fmt_time_natural(merged["end_time"])

    summary = f"Sửa '{cur['title']}' thành {merged['title']} vào {d_nat}, từ {s_nat} đến {e_nat}"
    return _stage(conn, {
        "action": "update",
        "event_id": event_id,
        "revision": cur["revision"],
        "payload": changes,
    }, summary)


@register_function(
    name="delete_calendar_event",
    description="ĐỀ XUẤT xóa lịch.",
    parameters={"event_id": {"type": "string", "required": True}},
)
async def delete_calendar_event(event_id) -> ActionResponse:
    conn, err = _conn()
    if err:
        return err
    async with AsyncSessionLocal() as db:
        cur = await cal.get_event(db, event_id, device_id=None)
    if not cur:
        return ActionResponse(Action.ERROR, result="Không tìm thấy lịch.")

    d_nat = _fmt_date_natural(cur["date"])
    s_nat = _fmt_time_natural(cur["start_time"])
    e_nat = _fmt_time_natural(cur["end_time"])

    summary = f"Xóa lịch {cur['title']} vào {d_nat}, từ {s_nat} đến {e_nat}"
    return _stage(conn, {
        "action": "delete",
        "event_id": event_id,
        "revision": cur["revision"],
    }, summary)


async def execute_pending(conn, token: str) -> str:
    """Consume and apply a staged proposal using its single-use confirmation token."""
    pending = getattr(conn, "_pending_calendar", None)
    if not pending:
        return "Không có đề xuất còn hiệu lực để xác nhận. Hãy yêu cầu lại."
    if time.monotonic() >= pending["expires_at"]:
        conn._pending_calendar = None
        return "Đề xuất lịch đã hết hạn. Hãy yêu cầu lại."
    if not isinstance(token, str) or not secrets.compare_digest(token, pending["token"]):
        return "Mã xác nhận không đúng phiên hoặc đã hết hiệu lực."
    # Consume before I/O, including failed/conflicting writes, to prevent replay.
    conn._pending_calendar = None
    try:
        async with AsyncSessionLocal() as db:
            if pending["action"] == "create":
                ev = await cal.create_event(db, pending["payload"], device_id=None)
                return f"Đã thêm lịch {ev['title']} vào {_fmt_date_natural(ev['date'])}, từ {_fmt_time_natural(ev['start_time'])} đến {_fmt_time_natural(ev['end_time'])}."
            if pending["action"] == "update":
                ev = await cal.update_event(db, pending["event_id"], pending["payload"],
                                            pending["revision"], device_id=None)
                return f"Đã cập nhật lịch {ev['title']} vào {_fmt_date_natural(ev['date'])}, từ {_fmt_time_natural(ev['start_time'])} đến {_fmt_time_natural(ev['end_time'])}."
            if pending["action"] == "delete":
                await cal.delete_event(db, pending["event_id"], pending["revision"],
                                       device_id=None)
                return "Đã xóa lịch trình đó rồi nhé."
    except cal.CalendarConflict as e:
        return f"Không thể lưu: {e}"
    except cal.CalendarError as e:
        return f"Dữ liệu không hợp lệ: {e}"
    except Exception as e:
        logger.exception(f"execute_pending: {e}")
        return "Có lỗi khi thao tác."
    finally:
        conn._pending_calendar = None
    return ""
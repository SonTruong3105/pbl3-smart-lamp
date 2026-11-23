"""WebSocket route — Device + Session tracking + IoT 2-way Sync."""
import asyncio
import json
import time as _t
import uuid
from collections import OrderedDict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.connection import ConnectionHandler
from app.core.logger import get_session_logger
from app.config import config
from app.schemas.websocket import HelloMessage, TextMessage
from app.core.device_hub import get_device_hub

router = APIRouter()

_active_handlers: dict = {}
_background_tasks: set[asyncio.Task] = set()
_rate_limit = OrderedDict()
_RL_WINDOW = 10.0
_RL_MAX = 5
_RL_MAX_KEYS = 10000


def _spawn_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _check_rate_limit(key: str) -> bool:
    now = _t.time()
    expired_keys = [
        k for k, ts in _rate_limit.items()
        if not ts or (now - ts[-1]) >= _RL_WINDOW
    ]
    for k in expired_keys:
        _rate_limit.pop(k, None)

    times = _rate_limit.pop(key, [])
    times[:] = [t for t in times if (now - t) < _RL_WINDOW]
    if len(times) >= _RL_MAX:
        _rate_limit[key] = times
        return False

    times.append(now)
    while len(_rate_limit) >= _RL_MAX_KEYS:
        _rate_limit.popitem(last=False)
    _rate_limit[key] = times
    return True


@router.get("/api/sessions")
async def list_sessions_api():
    from sqlalchemy import select
    from app.models import Session
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Session).order_by(Session.id.desc()).limit(50))
        return {
            "sessions": [
                {"id": s.id, "device_id": s.device_id, "started_at": str(s.started_at)}
                for s in res.scalars().all()
            ]
        }


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages_api(session_id: int):
    async with AsyncSessionLocal() as db:
        msgs = await chat_service.get_session_messages(db, session_id)
        return {
            "messages": [{"role": m.role, "content": m.content} for m in msgs[-50:]]
        }


async def _relay_to_esp32(esp32_handler, text: str, ws, log):
    """Relay text đến ESP32 + save messages."""
    try:
        turn_id = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            await chat_service.save_message(
                db, esp32_handler.session_id, "user", text, turn_id=turn_id
            )

        task = getattr(esp32_handler, "_pipeline_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        await esp32_handler.handle_text(text)

        bot_msg = esp32_handler.dialogue.last_assistant()
        if bot_msg and bot_msg.content:
            async with AsyncSessionLocal() as db:
                await chat_service.save_message(
                    db, esp32_handler.session_id, "assistant", bot_msg.content,
                    audio_bytes=esp32_handler.get_captured("bot_mp3"),
                    audio_ext="mp3", turn_id=turn_id
                )
                esp32_handler._captured["bot_mp3_parts"] = []
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception(f"relay error: {e}")
        try:
            await ws.send_json({"type": "error", "text": f"ESP32 lỗi: {e}"})
        except Exception:
            pass


async def _push_lamp_mcp_to_esp32(esp32_handler, data: dict):
    """Gửi lệnh điều khiển đèn chuẩn MCP (Lamp.*) xuống ESP32."""
    on = bool(data.get("on", False))
    if not on:
        await esp32_handler.transport.send_json({
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": int(uuid.uuid4().int % 100000),
                "method": "tools/call",
                "params": {"name": "Lamp.TurnOff", "arguments": {}},
            },
        })
        return

    brightness = max(0, min(100, int(data.get("brightness", 80))))
    cct_raw = int(data.get("cct", 50))
    cct = max(0, min(100, round((cct_raw - 3000) / 30)
                              if cct_raw >= 1000 else cct_raw))

    await esp32_handler.transport.send_json({
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": int(uuid.uuid4().int % 100000),
            "method": "tools/call",
            "params": {"name": "Lamp.TurnOn", "arguments": {}},
        },
    })
    # Firmware nhận value theo phần trăm ấm/lạnh, không nhận Kelvin.
    await esp32_handler.transport.send_json({
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": int(uuid.uuid4().int % 100000),
            "method": "tools/call",
            "params": {"name": "Lamp.SetColorTemp", "arguments": {"value": cct}},
        },
    })
    await esp32_handler.transport.send_json({
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": int(uuid.uuid4().int % 100000),
            "method": "tools/call",
            "params": {"name": "Lamp.SetBrightness", "arguments": {"value": brightness}},
        },
    })


async def _request_esp32_sync(esp32_handler):
    """Yêu cầu ESP32 gửi ngay trạng thái đèn + cảm biến hiện tại."""
    try:
        await esp32_handler.transport.send_json({
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": int(uuid.uuid4().int % 100000),
                "method": "tools/call",
                "params": {"name": "Lamp.GetState", "arguments": {}},
            },
        })
        await esp32_handler.transport.send_json({
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": int(uuid.uuid4().int % 100000),
                "method": "tools/call",
                "params": {"name": "self.get_environment", "arguments": {}},
            },
        })
    except Exception:
        pass


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()

    try:
        hello_raw = await ws.receive_text()
        hello = json.loads(hello_raw)
    except Exception:
        await ws.send_json({"type": "error", "text": "Expected hello"})
        await ws.close()
        return

    try:
        hello_model = HelloMessage.model_validate(hello)
    except Exception:
        await ws.send_json({"type": "error", "text": "Expected hello"})
        await ws.close()
        return

    device_id = hello_model.device_id
    client_session_id = hello_model.session_id
    force_new = hello_model.force_new

    log = get_session_logger(None, device_id)
    log.info(f"🔌 Client kết nối | device={device_id} | req_session={client_session_id}")

    client_ip = ws.client.host if ws.client else "unknown"
    rl_key = f"{client_ip}:{device_id}"
    if not _check_rate_limit(rl_key):
        log.error(f"🚨 Rate limit: {rl_key} — chặn")
        try:
            await ws.send_json({
                "type": "error",
                "text": "Quá nhiều kết nối. Đóng tab và mở lại.",
            })
            await ws.close(code=1013)
        except Exception:
            pass
        return

    prev = _active_handlers.get(device_id)
    if prev is not None:
        log.warning(
            f"⚠️ Device {device_id} có handler cũ — cho phép coexist "
            f"(tránh vòng lặp reconnect)"
        )

    session_id = None
    handler = None
    is_new = False
    hub = get_device_hub()

    try:
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "browser")
            session, is_new = await chat_service.resume_or_create_session(
                db, device_id, client_session_id, force_new=force_new
            )
            session_id = session.id

        log = get_session_logger(session_id, device_id)
        log.info(f"{'📝 Session mới' if is_new else '♻️  Tiếp tục session'} #{session_id}")

        await ws.send_json({
            "type": "session",
            "session_id": session_id,
            "is_new": is_new,
            "device_id": device_id,
        })

        handler = ConnectionHandler(ws, session_id, device_id)
        _active_handlers[device_id] = handler

        if not is_new:
            keep = config.llm_history_keep * 2
            async with AsyncSessionLocal() as db:
                history = await chat_service.get_session_history(
                    db, session_id, limit=keep,
                )
            handler.load_history(history)
            log.info(f"♻️  Load {min(len(history), keep)}/{len(history)} messages")

        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 Client disconnect")
                break

            if "text" in message and message["text"]:
                data = json.loads(message["text"])

                if data.get("type") == "link":
                    esp32_id = (data.get("esp32_device_id") or "").strip()
                    if not esp32_id:
                        await ws.send_json({"type": "error", "text": "Thiếu esp32_device_id"})
                        continue
                    esp32_handler = hub.get_esp32(esp32_id)
                    if not esp32_handler:
                        await ws.send_json({
                            "type": "error",
                            "text": f"ESP32 {esp32_id} chưa kết nối",
                        })
                        continue
                    hub.link_chat(device_id, esp32_id, ws)
                    await ws.send_json({
                        "type": "link_status",
                        "linked": True,
                        "esp32_device_id": esp32_id,
                    })
                    log.info(f"🔗 Linked {device_id} → {esp32_id}")
                    _spawn_task(_request_esp32_sync(esp32_handler))
                    continue

                if data.get("type") == "unlink":
                    hub.unlink_chat(device_id)
                    await ws.send_json({"type": "link_status", "linked": False})
                    log.info(f"🔗 Unlinked {device_id}")
                    continue

                if data.get("type") == "sync_request":
                    link = hub.get_chat_by_web(device_id)
                    if link:
                        esp32_handler = hub.get_esp32(link[0])
                        if esp32_handler:
                            _spawn_task(_request_esp32_sync(esp32_handler))
                    continue

                if data.get("type") == "lamp_state":
                    link = hub.get_chat_by_web(device_id)
                    if not link:
                        await ws.send_json({"type": "error", "text": "Chưa link ESP32"})
                        continue
                    esp32_id, _ = link
                    esp32_handler = hub.get_esp32(esp32_id)
                    if not esp32_handler:
                        await ws.send_json({"type": "error", "text": "ESP32 mất kết nối"})
                        continue

                    try:
                        await _push_lamp_mcp_to_esp32(esp32_handler, data)
                    except Exception as e:
                        await ws.send_json({"type": "error", "text": f"Lỗi gửi ESP32: {e}"})
                    continue

                if data.get("type") == "message":
                    raw_text = (data.get("text") or "").strip() if isinstance(data, dict) else ""
                    if not raw_text:
                        log.debug("Empty message — silent skip")
                        continue
                    try:
                        text_model = TextMessage.model_validate(data)
                    except Exception:
                        await ws.send_json({"type": "error", "text": "Invalid message"})
                        continue
                    user_text = text_model.text.strip()

                    link_info = hub.get_chat_by_web(device_id)
                    if link_info:
                        esp32_id, _lw = link_info
                        esp32_handler = hub.get_esp32(esp32_id)
                        if not esp32_handler:
                            await ws.send_json({
                                "type": "error",
                                "text": f"ESP32 {esp32_id} mất kết nối",
                            })
                            continue
                        log.info(f"📨 Relay → ESP32 {esp32_id}: {user_text!r}")
                        _spawn_task(_relay_to_esp32(esp32_handler, user_text, ws, log))
                        continue

                    turn_id = uuid.uuid4().hex[:8]
                    async with AsyncSessionLocal() as db:
                        await chat_service.save_message(db, session_id, "user", user_text, turn_id=turn_id)

                    try:
                        full_response = await handler.handle_text(user_text)
                        if full_response:
                            await handler.wait_for_quick_audio()
                            await handler.flush_pending_music()
                            async with AsyncSessionLocal() as db:
                                await chat_service.save_message(
                                    db, session_id, "assistant", full_response,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3", turn_id=turn_id
                                )
                            handler._captured["bot_mp3_parts"] = []
                    except asyncio.CancelledError:
                        log.info("⏹️ handle_text cancelled")
                    except Exception as e:
                        log.exception(f"handle_text lỗi: {e}")
                    finally:
                        try:
                            await handler.send_end()
                        except Exception:
                            pass

                elif data.get("type") == "clear_session":
                    log.info("🔄 Client yêu cầu session mới")
                    async with AsyncSessionLocal() as db:
                        await chat_service.close_session(db, session_id)
                        session = await chat_service.create_session(db, device_id)
                        is_new = True
                        session_id = session.id
                    log = get_session_logger(session_id, device_id)

                    handler = ConnectionHandler(ws, session_id, device_id)
                    _active_handlers[device_id] = handler

                    await ws.send_json({
                        "type": "session",
                        "session_id": session_id,
                        "is_new": True,
                        "device_id": device_id,
                    })

            elif "bytes" in message and message["bytes"]:
                audio_bytes = message["bytes"]
                log.info(f"🎤 Audio: {len(audio_bytes)} bytes")

                try:
                    turn_id = uuid.uuid4().hex[:8]
                    user_text = await handler.handle_voice(audio_bytes)
                    if user_text:
                        async with AsyncSessionLocal() as db:
                            await chat_service.save_message(
                                db, session_id, "user", user_text,
                                audio_bytes=handler.get_captured("user_wav"),
                                audio_ext="wav", turn_id=turn_id
                            )
                            bot_msg = handler.dialogue.last_assistant()
                            if bot_msg and bot_msg.content:
                                await chat_service.save_message(
                                    db, session_id, "assistant", bot_msg.content,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3", turn_id=turn_id
                                )
                            handler._captured["bot_mp3_parts"] = []
                except asyncio.CancelledError:
                    log.info("⏹️ handle_voice cancelled")
                except Exception as e:
                    log.exception(f"handle_voice lỗi: {e}")
                finally:
                    try:
                        await handler.send_end()
                    except Exception:
                        pass

    except WebSocketDisconnect:
        log.info("🔌 Client ngắt (WSDisconnect)")
    except RuntimeError as e:
        log.info(f"🔌 Client ngắt: {e}")
    except asyncio.CancelledError:
        log.info("⏹️ chat_ws cancelled")
    except Exception as e:
        log.exception(f"❌ WS lỗi: {type(e).__name__}: {e}")
    finally:
        try:
            hub.unlink_chat(device_id)
        except Exception:
            pass

        if _active_handlers.get(device_id) is handler:
            _active_handlers.pop(device_id, None)

        if handler is not None:
            try:
                await handler.abort()
            except (Exception, asyncio.CancelledError):
                pass

        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception as e:
                log.warning(f"⚠️ Không đóng được session: {e}")
        log.info(f"🔌 Session #{session_id} đóng")
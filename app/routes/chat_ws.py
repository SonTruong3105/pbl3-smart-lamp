"""WebSocket route — Device + Session tracking."""
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.connection import ConnectionHandler
from app.core.logger import get_session_logger


router = APIRouter()


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

    if hello.get("type") != "hello":
        await ws.send_json({"type": "error", "text": "Expected hello"})
        await ws.close()
        return

    device_id = hello.get("device_id") or "browser-anon"
    client_session_id = hello.get("session_id")

    log = get_session_logger(None, device_id)
    log.info(f"🔌 Client kết nối | device={device_id} | req_session={client_session_id}")

    session_id = None
    handler = None
    is_new = False   # ✅ FIX: tránh undefined

    try:
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "browser")
            session, is_new = await chat_service.resume_or_create_session(
                db, device_id, client_session_id,
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

        if not is_new:
            async with AsyncSessionLocal() as db:
                history = await chat_service.get_session_history(db, session_id)
            handler.load_history(history)
            log.info(f"♻️  Load {len(history)} message từ session cũ")

        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 Client disconnect")
                break

            if "text" in message and message["text"]:
                data = json.loads(message["text"])

                if data.get("type") == "message":
                    user_text = data.get("text", "").strip()
                    if not user_text:
                        continue

                    async with AsyncSessionLocal() as db:
                        await chat_service.save_message(db, session_id, "user", user_text)

                    try:
                        full_response = await handler.handle_text(user_text)
                        if full_response:
                            async with AsyncSessionLocal() as db:
                                await chat_service.save_message(
                                    db, session_id, "assistant", full_response,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3",
                                )
                    except Exception as e:
                        log.exception(f"handle_text lỗi: {e}")
                    finally:
                        await handler.send_end()

                elif data.get("type") == "clear_session":
                    log.info("🔄 Client yêu cầu session mới")
                    async with AsyncSessionLocal() as db:
                        await chat_service.close_session(db, session_id)
                        session, is_new = await chat_service.resume_or_create_session(
                            db, device_id, None,
                        )
                        session_id = session.id
                    log = get_session_logger(session_id, device_id)

                    handler = ConnectionHandler(ws, session_id, device_id)

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
                    user_text = await handler.handle_voice(audio_bytes)
                    if user_text:
                        async with AsyncSessionLocal() as db:
                            await chat_service.save_message(
                                db, session_id, "user", user_text,
                                audio_bytes=handler.get_captured("user_wav"),
                                audio_ext="wav",
                            )
                            bot_msg = handler.dialogue.last_assistant()
                            if bot_msg and bot_msg.content:
                                await chat_service.save_message(
                                    db, session_id, "assistant", bot_msg.content,
                                    audio_bytes=handler.get_captured("bot_mp3"),
                                    audio_ext="mp3",
                                )
                except Exception as e:
                    log.exception(f"handle_voice lỗi: {e}")
                finally:
                    await handler.send_end()

    except WebSocketDisconnect:
        log.info("🔌 Client ngắt (WSDisconnect)")
    except RuntimeError as e:
        log.info(f"🔌 Client ngắt: {e}")
    except Exception as e:
        log.exception(f"❌ WS lỗi: {type(e).__name__}: {e}")
    finally:
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception as e:
                log.warning(f"⚠️ Không đóng được session: {e}")
        log.info(f"🔌 Session #{session_id} đóng")
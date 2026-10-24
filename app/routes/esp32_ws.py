"""
WebSocket endpoint cho ESP32 — giao thức Xiaozhi v1 + VAD.
"""
import asyncio
import io
import json
import time
import wave
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import config
from app.core.esp32_connection import ESP32ConnectionHandler
from app.core.protocols import WebSocketTransport
from app.core.logger import get_session_logger
from app.core.utils.opus_codec import OpusCodec
from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.wake_word import matches_wake_word, DEFAULT_WAKE_WORDS
from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager

router = APIRouter()

# Biến toàn cục để lưu âm thanh debug
debug_pcm_buffer = bytearray()

# ⭐ Wake word cooldown
_wake_last_time = 0.0

def _make_vad():
    vad_cfg = config.vad_config
    if config.vad_provider == "silero":
        from app.core.providers.vad.silero import SileroVAD
        model_dir = vad_cfg.get("model_dir", "models/snakers4_silero-vad")
        return SileroVAD(
            model_path=f"{model_dir}/silero_vad.onnx",
            sample_rate=16000,
            threshold=vad_cfg.get("threshold", 0.5),
            threshold_low=vad_cfg.get("threshold_low", 0.2),
            silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
            min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
        )
    else:
        from app.core.providers.vad.energy import EnergyVAD
        return EnergyVAD(
            sample_rate=16000,
            frame_duration_ms=config.frame_duration,
            silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
            min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
            energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
            initial_threshold=vad_cfg.get("initial_threshold", 500.0),
            hangover_ms=vad_cfg.get("hangover_ms", 200),
            pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
            post_speech_ms=vad_cfg.get("post_speech_ms", 300),
        )

def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """PCM int16 mono → WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _respond_wake_word(handler, log):
    """Phát câu chào ngắn khi ESP32 phát hiện wake word."""
    global _wake_last_time
    import time, random

    now = time.time()
    cooldown = float(config._get("wake_word", "cooldown_sec", default=8.0))
    if now - _wake_last_time < cooldown:
        log.debug(f"🔕 Wake word cooldown ({now - _wake_last_time:.1f}s)")
        return
    _wake_last_time = now

    responses = config._get("wake_word", "responses", default=["Dạ!"])
    reply = random.choice(responses)
    log.info(f"🔔 Wake word → TTS: {reply!r}")

    try:
        audio = await handler.tts.synthesize(reply)
        if audio:
            await handler._send_callback({
                "type": "audio",
                "index": 1,
                "total": 1,
                "sentence": reply,
                "data": audio,
            })
    except Exception as e:
        log.warning(f"Wake TTS lỗi: {e}")



@router.websocket("/xiaozhi/v1/")
async def esp32_ws(ws: WebSocket):
    global debug_pcm_buffer
    await ws.accept()

    device_id = ws.headers.get("Device-Id", "esp32-unknown")
    log = get_session_logger(None, device_id)
    log.info(f"🔌 ESP32 kết nối | device={device_id}")

    session_id = None
    handler = None
    opus = OpusCodec(sample_rate=16000, channels=1)
    vad = _make_vad()

    process_task: Optional[asyncio.Task] = None
    listen_mode = "auto"
    debug_pcm_buffer = bytearray()

    try:
        # ============ 1. Hello ============
        raw = await ws.receive_text()
        hello = json.loads(raw)
        log.info(f"📨 Hello: {hello.get('type')} | version={hello.get('version')}")

        if hello.get("type") != "hello":
            await ws.close(code=1002)
            return

        device_id = (ws.headers.get("Device-Id") or hello.get("device_id") or hello.get("deviceId") or device_id)

        # ============ 2. Session ============
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "esp32")
            session, is_new = await chat_service.resume_or_create_session(db, device_id, None)
            session_id = session.id

        log = get_session_logger(session_id, device_id)
        log.info(f"📝 Session #{session_id} ({'mới' if is_new else 'tiếp tục'})")

        # ============ 3. Hello response ============
        await ws.send_json({
            "type": "hello",
            "version": 1,
            "session_id": str(session_id),
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 24000,
                "channels": 1,
                "frame_duration": 60,
            },
        })

        # ============ 4. Handler ============
        transport = WebSocketTransport(ws)
        handler = ESP32ConnectionHandler(transport, session_id, device_id)

        # Đăng ký transport cho Device MCP
        mcp_manager = get_device_mcp_manager()
        mcp_manager.attach(device_id, transport)

        # ============ 5. Message loop ============
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 ESP32 disconnect")
                # Lưu nốt âm thanh còn lại khi ngắt kết nối
                if len(debug_pcm_buffer) > 0:
                    Path("data/audio_test").mkdir(parents=True, exist_ok=True)
                    filename = str(Path("data/audio_test") / f"debug_{int(time.time())}.wav")
                    with wave.open(filename, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(debug_pcm_buffer)
                    log.info(f"🎙️ Đã lưu âm thanh cuối vào file: {filename}")
                if process_task and not process_task.done():
                    process_task.cancel()
                break

            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type")
                if msg_type == "listen":
                    listen_mode = (data.get("mode") or "auto").lower()
                    listen_state = (data.get("state") or "").lower()
                    vad.reset()
                    log.info(f"🎤 Listen mode={listen_mode} state={listen_state}")

                    # ⭐ Phản hồi câu chào khi ESP32 phát hiện wake word
                    if config._get("wake_word", "enabled", default=False):
                        if listen_state in ("start", "detect"):
                            asyncio.create_task(_respond_wake_word(handler, log))
                elif msg_type == "abort":
                    if process_task and not process_task.done():
                        process_task.cancel()
                    vad.reset()
                elif msg_type == "mcp":
                    # Xử lý message MCP từ ESP32 (initialize, tools/list, reply tools/call)
                    payload = data.get("payload", {})
                    method = payload.get("method")
                    req_id = payload.get("id")

                    if method == "initialize":
                        # Reply initialize để ESP32 tiếp tục
                        await ws.send_json({
                            "type": "mcp",
                            "payload": {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {"tools": {}},
                                    "serverInfo": {"name": "xiaozhi-ce", "version": "2.0.0"},
                                },
                            },
                        })
                        log.info(f"📡 MCP: initialize từ {device_id}")

                    elif method == "tools/list":
                        # Đăng ký tool động
                        tools_list = payload.get("result", {}).get("tools", [])
                        await mcp_manager.register_device_tools(device_id, tools_list)
                        await ws.send_json({
                            "type": "mcp",
                            "payload": {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {"tools": tools_list},
                            },
                        })
                        log.info(f"📡 MCP: nhận {len(tools_list)} tool từ {device_id}")

                    elif method == "notifications/initialized":
                        pass  # không cần reply

                    else:
                        # Reply cho tools/call
                        mcp_manager.handle_mcp_message(device_id, payload)

                elif msg_type == "end" and listen_mode == "manual":
                    if vad.has_speech():
                        pcm = vad.get_audio()
                        vad.reset()
                        if pcm and (process_task is None or process_task.done()):
                            process_task = asyncio.create_task(_process_vad_audio(handler, session_id, log, pcm))

            elif "bytes" in message and message["bytes"]:
                opus_frame = message["bytes"]
                try:
                    pcm = opus.decode(opus_frame)
                except Exception as e:
                    log.warning(f"⚠️ Opus decode lỗi: {e}")
                    continue

                # 🚨 LƯU ÂM THANH DEBUG: Cứ tích lũy đủ 5 giây thì lưu ra file 1 lần
                debug_pcm_buffer.extend(pcm)
                if len(debug_pcm_buffer) >= 16000 * 2 * 5:
                    Path("data/audio_test").mkdir(parents=True, exist_ok=True)
                    filename = str(Path("data/audio_test") / f"debug_{int(time.time())}.wav")
                    with wave.open(filename, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(debug_pcm_buffer)
                    log.info(f"🎙️ Đã lưu 5s âm thanh vào file: {filename}")
                    debug_pcm_buffer = bytearray()

                # VAD
                is_end = vad.push(pcm)
                if is_end:
                    log.info(f"🎯 VAD end-of-speech | stats={vad.get_stats()}")
                    pcm_data = vad.get_audio()
                    vad.reset()
                    if pcm_data and (process_task is None or process_task.done()):
                        process_task = asyncio.create_task(_process_vad_audio(handler, session_id, log, pcm_data))
                    elif pcm_data:
                        log.warning("⚠️ Pipeline đang chạy, bỏ qua VAD end")

    except WebSocketDisconnect:
        log.info("🔌 ESP32 ngắt kết nối")
    except Exception as e:
        log.exception(f"❌ ESP32 WS lỗi: {type(e).__name__}: {e}")
    finally:
        if process_task and not process_task.done():
            process_task.cancel()
        # Gỡ Device MCP
        try:
            get_device_mcp_manager().detach(device_id)
        except Exception:
            pass
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception:
                pass
        log.info(f"🔌 Session #{session_id} đóng")


async def _process_vad_audio(handler, session_id, log, pcm: bytes):
    try:
        t0 = time.perf_counter()
        log.info(f"🎵 VAD audio: PCM {len(pcm)}b (~{len(pcm) / 2 / 16000:.2f}s)")
        wav = _pcm_to_wav(pcm, sample_rate=16000)
        user_text = await handler.handle_voice_wav(wav)
        pipeline_ms = (time.perf_counter() - t0) * 1000
        log.info(f"✅ Pipeline [{pipeline_ms:.0f}ms] | user='{user_text}'")

        # ⭐ LƯU USER WAV + BOT MP3 VÀO DB (data/user/, data/bot/)
        if user_text:
            try:
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
                log.info(f"💾 Đã lưu user_wav + bot_mp3 vào DB")
            except Exception as e:
                log.warning(f"⚠️ Không lưu được audio vào DB: {e}")
    except asyncio.CancelledError:
        log.info("⏹️ _process_vad_audio bị cancel")
        raise
    except Exception as e:
        log.exception(f"❌ Xử lý VAD audio lỗi: {e}")
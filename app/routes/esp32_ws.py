"""
WebSocket endpoint cho ESP32 — giao thức Xiaozhi v1 + VAD.
"""
import asyncio
import io
import json
import time
import wave
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
router = APIRouter()


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


@router.websocket("/xiaozhi/v1/")
async def esp32_ws(ws: WebSocket):
    """WebSocket endpoint cho ESP32 với VAD."""
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

    try:
        # ============ 1. Hello ============
        raw = await ws.receive_text()
        hello = json.loads(raw)
        log.info(f"📨 Hello: {hello.get('type')} | version={hello.get('version')}")

        if hello.get("type") != "hello":
            log.error("❌ Message đầu không phải hello")
            await ws.close(code=1002)
            return

        # ✅ Đọc device_id từ header hoặc hello
        device_id = (
            ws.headers.get("Device-Id")
            or hello.get("device_id")
            or hello.get("deviceId")
            or device_id
        )

        # ============ 2. Session ============
        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "esp32")
            session, is_new = await chat_service.resume_or_create_session(
                db, device_id, None,
            )
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
        handler = ESP32ConnectionHandler(WebSocketTransport(ws), session_id, device_id)

        # ============ 5. Message loop ============
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                log.info("🔌 ESP32 disconnect")
                if process_task and not process_task.done():
                    process_task.cancel()
                if vad.has_speech():
                    log.info("📤 Xử lý audio còn sót trước khi đóng")
                    pcm = vad.get_audio()
                    vad.reset()
                    if pcm:
                        await _process_vad_audio(handler, session_id, log, pcm)
                break

            # ----- TEXT: JSON control -----
            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    log.warning(f"⚠️ Text không phải JSON: {message['text'][:80]}")
                    continue

                msg_type = data.get("type")

                if msg_type == "listen":
                    mode = (data.get("mode") or "auto").lower()
                    listen_mode = mode
                    wake_text = data.get("text", "")

                    # Wake word gate
                    from app.config import config as _cfg
                    wake_enabled = _cfg._get("wake_word", "enabled", default=True)
                    wake_mode = _cfg._get("wake_word", "mode", default="device")
                    wake_words = _cfg._get("wake_word", "words", default=DEFAULT_WAKE_WORDS)

                    if wake_enabled and wake_mode == "device":
                        if not matches_wake_word(wake_text, wake_words):
                            log.info(f"⏭️ Bỏ qua — wake word sai: {wake_text!r}")
                            await ws.send_json({
                                "type": "status",
                                "text": "Cần gọi 'đèn ơi' trước",
                            })
                            continue

                    if wake_text:
                        log.info(f"🎤 Wake word OK: '{wake_text}'")
                    vad.reset()
                    log.info(f"🎤 Listen mode={mode}")

                elif msg_type == "abort":
                    if process_task and not process_task.done():
                        process_task.cancel()
                        try:
                            await process_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        process_task = None
                    handler.abort()
                    vad.reset()
                    log.info("⏹️  ESP32 abort — đã huỷ pipeline")

                elif msg_type == "end":
                    if listen_mode == "manual":
                        if vad.has_speech():
                            pcm = vad.get_audio()
                            vad.reset()
                            if pcm:
                                if process_task and not process_task.done():
                                    log.warning("⚠️ Đang xử lý, bỏ qua end")
                                else:
                                    process_task = asyncio.create_task(
                                        _process_vad_audio(handler, session_id, log, pcm)
                                    )
                        else:
                            vad.reset()

                # ✅ Realtime: stream liên tục, bỏ VAD
                elif msg_type == "realtime":
                    log.info("🎤 Realtime mode — bỏ VAD")

                else:
                    log.debug(f"📨 ESP32 → {msg_type}")

            # ----- BINARY: Opus frames -----
            elif "bytes" in message and message["bytes"]:
                opus_frame = message["bytes"]
                try:
                    pcm = opus.decode(opus_frame)
                except Exception as e:
                    log.warning(f"⚠️ Opus decode lỗi: {e}")
                    continue

                if listen_mode == "manual":
                    vad.push(pcm)
                    continue

                is_end = vad.push(pcm)
                if is_end:
                    log.info(f"🎯 VAD end-of-speech | stats={vad.get_stats()}")
                    pcm_data = vad.get_audio()
                    vad.reset()
                    if pcm_data and (process_task is None or process_task.done()):
                        process_task = asyncio.create_task(
                            _process_vad_audio(handler, session_id, log, pcm_data)
                        )
                    elif pcm_data:
                        log.warning("⚠️ Pipeline đang chạy, bỏ qua VAD end")

    except WebSocketDisconnect:
        log.info("🔌 ESP32 ngắt kết nối")
    except Exception as e:
        log.exception(f"❌ ESP32 WS lỗi: {type(e).__name__}: {e}")
    finally:
        if process_task and not process_task.done():
            process_task.cancel()
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception:
                pass
        log.info(f"🔌 Session #{session_id} đóng")


async def _process_vad_audio(
    handler: ESP32ConnectionHandler,
    session_id: int,
    log,
    pcm: bytes,
):
    """Convert WAV → pipeline."""
    try:
        t0 = time.perf_counter()

        log.info(
            f"🎵 VAD audio: PCM {len(pcm)}b "
            f"(~{len(pcm) / 2 / 16000:.2f}s)"
        )

        wav = _pcm_to_wav(pcm, sample_rate=16000)
        user_text = await handler.handle_voice_wav(wav)

        pipeline_ms = (time.perf_counter() - t0) * 1000
        log.info(f"✅ Pipeline [{pipeline_ms:.0f}ms] | user='{user_text}'")

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

    except asyncio.CancelledError:
        log.info("⏹️ _process_vad_audio bị cancel")
        raise
    except Exception as e:
        log.exception(f"❌ Xử lý VAD audio lỗi: {e}")
"""WebSocket endpoint cho ESP32 — 1 luồng hợp nhất thoại + MCP + trạng thái/cảm biến."""
import asyncio, io, json, time, wave, uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import config
from app.core.esp32_connection import ESP32ConnectionHandler
from app.core.protocols import WebSocketTransport
from app.core.protocols.binary import unwrap_opus_frame
from app.core.logger import get_session_logger
from app.core.utils.opus_codec import OpusCodec
from app.database import AsyncSessionLocal
from app.services import chat as chat_service
from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
from app.core.device_auth import verify_device_token
from app.core.device_hub import SENSOR_KEYS, get_device_hub
from app.routes.device_sync_ws import normalize_sensor_payload, _push_sensor_to_web

router = APIRouter()
_wake_greeted_devices: set[str] = set()


def _make_vad():
    vad_cfg = config.vad_config
    if config.vad_provider == "silero":
        from app.core.providers.vad.silero import SileroVAD
        model_dir = vad_cfg.get("model_dir", "models/snakers4_silero-vad")
        return SileroVAD(
            model_path=f"{model_dir}/silero_vad.onnx", sample_rate=16000,
            threshold=vad_cfg.get("threshold", 0.5),
            threshold_low=vad_cfg.get("threshold_low", 0.2),
            silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
            min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
        )
    from app.core.providers.vad.energy import EnergyVAD
    return EnergyVAD(
        sample_rate=16000, frame_duration_ms=config.frame_duration,
        silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
        min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
        energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
        initial_threshold=vad_cfg.get("initial_threshold", 500.0),
        hangover_ms=vad_cfg.get("hangover_ms", 200),
        pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
        post_speech_ms=vad_cfg.get("post_speech_ms", 300),
    )


def _pcm_to_wav(pcm, sample_rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _respond_wake_word(handler, log):
    """Play the configured acknowledgement once per device/server lifetime."""
    device_id = handler.device_id
    if device_id in _wake_greeted_devices:
        return

    reply = config._get("wake_word", "iconic_response", default="Dạ em đây!")
    try:
        audio = await handler.tts.synthesize(reply)
        if not audio:
            return
        await handler._send_callback({
            "type": "audio", "index": 1, "total": 1,
            "sentence": reply, "data": audio,
        })
        await handler._send_callback({"type": "tts_stop"})
        _wake_greeted_devices.add(device_id)
    except Exception as e:
        log.warning(f"Wake TTS lỗi: {e}")


def _extract_mcp_json_result(payload: dict) -> Optional[dict]:
    """Trích xuất dict JSON từ gói phản hồi MCP JSON-RPC của ESP32."""
    res = payload.get("result")
    if not isinstance(res, dict):
        return None
    if "content" in res and isinstance(res["content"], list):
        for item in res["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    parsed = json.loads(item["text"])
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
    return res


async def _broadcast_esp_state_to_web(device_id: str, parsed: dict):
    """Đẩy ngay trạng thái đèn hoặc cảm biến từ ESP32 sang các WebSocket Web đang link."""
    if not isinstance(parsed, dict):
        return

    hub = get_device_hub()
    target_sockets = [
        chat_ws for _web_id, chat_ws in hub.get_chats_by_device(device_id)
        if hasattr(chat_ws, "send_json")
    ]

    # 1. Phản hồi từ các tool Lamp.*
    if {"on", "brightness"}.issubset(parsed.keys()):
        hub.update_lamp(parsed, device_id=device_id)
        await hub.broadcast_sync(device_id, "lamp_update", parsed)
        msg = {
            "type": "lamp_sync",
            "esp32_device_id": device_id,
            "data": parsed,
            **parsed,
        }
        for chat_ws in target_sockets:
            try:
                await chat_ws.send_json(msg)
            except Exception:
                pass

    # 2. Phản hồi từ các tool cảm biến (self.get_environment)
    elif any(k in parsed for k in SENSOR_KEYS):
        hub.update_sensors(parsed, device_id=device_id)
        await hub.broadcast_sync(device_id, "sensor_update", parsed)
        msg = {
            "type": "sensor_update",
            "esp32_device_id": device_id,
            "data": parsed,
            **parsed,
        }
        for chat_ws in target_sockets:
            try:
                await chat_ws.send_json(msg)
            except Exception:
                pass


async def _bootstrap_device_mcp_and_sync(device_id: str):
    """Khám phá tool MCP rồi đồng bộ trạng thái đèn & cảm biến ban đầu qua 1 WS."""
    try:
        await asyncio.sleep(0.5)
        mgr = get_device_mcp_manager()
        await mgr.discover_tools(device_id)
        for method in ("Lamp.GetState", "self.get_environment"):
            try:
                await mgr.call_tool(device_id, method, {}, timeout=4.0)
            except Exception:
                pass
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


@router.websocket("/xiaozhi/v1/")
async def esp32_ws(ws: WebSocket):
    await ws.accept()
    device_id = ws.headers.get("Device-Id", "esp32-unknown")
    client_id = ws.headers.get("Client-Id", "")
    try:
        protocol_version = int(ws.headers.get("Protocol-Version", "1") or 1)
    except (TypeError, ValueError):
        protocol_version = 1
    log = get_session_logger(None, device_id)

    if config._get("server", "auth", "enabled", default=False):
        token = ws.headers.get("Device-Token", "")
        if not token:
            auth_header = ws.headers.get("Authorization", "")
            token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
        if not verify_device_token(device_id, token):
            log.warning(f"🚫 Auth fail: {device_id}")
            await ws.send_json({"type": "error", "text": "unauthorized"})
            await ws.close(code=1008)
            return

    log.info(f"🔌 ESP32 kết nối | device={device_id} | client={client_id or '-'} | proto=v{protocol_version}")
    hub = get_device_hub()
    session_id = None
    handler: Optional[ESP32ConnectionHandler] = None
    transport: Optional[WebSocketTransport] = None
    opus = OpusCodec(sample_rate=16000, channels=1)
    vad = _make_vad()
    process_task: Optional[asyncio.Task] = None
    bootstrap_task: Optional[asyncio.Task] = None
    listen_mode = "auto"
    debug_pcm_buffer = bytearray()
    save_debug = config._get("debug", "save_audio", default=False)

    try:
        raw = await ws.receive_text()
        hello = json.loads(raw)
        if hello.get("type") != "hello":
            await ws.close(code=1002)
            return
        hello_device_id = hello.get("device_id") or hello.get("deviceId")
        if config.auth_enabled and hello_device_id and hello_device_id != device_id:
            log.warning(f"🚫 Device identity mismatch: header={device_id}, hello={hello_device_id}")
            await ws.close(code=1008)
            return
        device_id = ws.headers.get("Device-Id") or hello_device_id or device_id
        try:
            device_version = int(hello.get("version", protocol_version) or 1) or 1
        except (TypeError, ValueError):
            device_version = protocol_version

        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "esp32")
            session, is_new = await chat_service.resume_or_create_session(db, device_id, None)
            session_id = session.id

        log = get_session_logger(session_id, device_id)
        log.info(f"📝 Session #{session_id} ({'mới' if is_new else 'tiếp tục'})")

        await ws.send_json({
            "type": "hello", "version": device_version, "session_id": str(session_id),
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": config.sample_rate,
                             "channels": 1, "frame_duration": 60}})

        transport = WebSocketTransport(ws, binary_version=device_version)
        handler = ESP32ConnectionHandler(transport, session_id, device_id)
        hub.register_esp32(device_id, handler)
        hub.register_active_device(device_id)
        try:
            await hub.broadcast_sync(device_id, "device_status", {"online": True})
        except Exception:
            pass
        try:
            from app.core.reminder_engine import get_engine
            await get_engine().reload()
        except Exception:
            pass

        mcp_manager = get_device_mcp_manager()
        mcp_manager.attach(device_id, transport, channel="audio")
        bootstrap_task = asyncio.create_task(_bootstrap_device_mcp_and_sync(device_id))

        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                if save_debug and debug_pcm_buffer:
                    Path("data/audio_test").mkdir(parents=True, exist_ok=True)
                    fn = str(Path("data/audio_test") /
                             f"debug_{device_id.replace(':', '-')}_{int(time.time())}.wav")
                    with wave.open(fn, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(debug_pcm_buffer)
                if process_task and not process_task.done():
                    process_task.cancel()
                break

            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type")

                if msg_type == "ping":
                    await transport.send_json({"type": "pong"})
                    continue
                elif msg_type == "ack":
                    rid = data.get("reminder_id", "")
                    if rid:
                        await handler.ack_reminder(rid)
                    continue

                if msg_type == "listen":
                    listen_mode = (data.get("mode") or "auto").lower()
                    listen_state = (data.get("state") or "").lower()
                    if listen_state == "detect":
                        vad.reset()
                        if config._get("wake_word", "enabled", default=False):
                            await _respond_wake_word(handler, log)
                            vad.reset()
                    elif listen_state == "start":
                        vad.reset()

                elif msg_type == "abort":
                    if process_task and not process_task.done():
                        process_task.cancel()
                    await handler.abort()
                    vad.reset()

                elif msg_type == "mcp":
                    payload = data.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    method = payload.get("method")
                    req_id = payload.get("id")
                    if "result" in payload or "error" in payload:
                        mcp_manager.handle_mcp_message(device_id, payload)
                        result = payload.get("result")
                        if isinstance(result, dict) and result.get("tools") is not None:
                            await mcp_manager.register_device_tools(
                                device_id, result["tools"]
                            )
                        parsed_res = _extract_mcp_json_result(payload)
                        if parsed_res:
                            asyncio.create_task(
                                _broadcast_esp_state_to_web(device_id, parsed_res)
                            )
                    elif method == "initialize":
                        await transport.send_json({"type": "mcp", "payload": {
                            "jsonrpc": "2.0", "id": req_id, "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "xiaozhi-ce", "version": "2.0.0"}}}})
                    elif method == "tools/list":
                        tl = payload.get("params", {}).get("tools") or payload.get("result", {}).get("tools", [])
                        if tl:
                            await mcp_manager.register_device_tools(device_id, tl)
                        await transport.send_json({"type": "mcp", "payload": {
                            "jsonrpc": "2.0", "id": req_id,
                            "result": {"tools": tl}}})
                    elif method == "notifications/sensor_state":
                        params = payload.get("params")
                        if isinstance(params, dict):
                            clean = normalize_sensor_payload(params) or params
                            asyncio.create_task(_broadcast_esp_state_to_web(device_id, clean))
                    elif method == "notifications/initialized":
                        pass
                    else:
                        mcp_manager.handle_mcp_message(device_id, payload)
                        parsed_res = _extract_mcp_json_result(payload)
                        if parsed_res:
                            asyncio.create_task(_broadcast_esp_state_to_web(device_id, parsed_res))

                elif msg_type == "sensor":
                    raw_sensor = data.get("data") if isinstance(data.get("data"), dict) else data
                    clean = normalize_sensor_payload(raw_sensor)
                    if clean:
                        hub.update_sensors(clean, device_id=device_id)
                        asyncio.create_task(_push_sensor_to_web(device_id, clean))

                elif msg_type == "lamp_state":
                    lamp_payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    if isinstance(lamp_payload, dict):
                        hub.update_lamp(lamp_payload, device_id=device_id)
                        asyncio.create_task(hub.broadcast_sync(device_id, "lamp_update", lamp_payload))

                elif msg_type == "end" and listen_mode == "manual":
                    if vad.has_speech():
                        pcm = vad.get_audio()
                        vad.reset()
                        if pcm and (process_task is None or process_task.done()):
                            process_task = asyncio.create_task(
                                _process_vad_audio(handler, session_id, log, pcm))

            elif "bytes" in message and message["bytes"]:
                opus_frame = unwrap_opus_frame(message["bytes"], device_version)
                if not opus_frame:
                    log.warning(f"⚠️ Binary frame v{device_version} không hợp lệ")
                    continue
                try:
                    pcm = opus.decode(opus_frame)
                except Exception as e:
                    log.warning(f"⚠️ Opus decode: {e}")
                    continue

                if save_debug:
                    debug_pcm_buffer.extend(pcm)
                    if len(debug_pcm_buffer) >= 16000 * 2 * 5:
                        Path("data/audio_test").mkdir(parents=True, exist_ok=True)
                        fn = str(Path("data/audio_test") /
                                 f"debug_{device_id.replace(':', '-')}_{int(time.time())}.wav")
                        with wave.open(fn, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(16000)
                            wf.writeframes(debug_pcm_buffer)
                        debug_pcm_buffer = bytearray()

                if vad.push(pcm):
                    log.info(f"🎯 VAD end | {vad.get_stats()}")
                    pcm_data = vad.get_audio()
                    vad.reset()
                    if pcm_data and (process_task is None or process_task.done()):
                        process_task = asyncio.create_task(
                            _process_vad_audio(handler, session_id, log, pcm_data))

    except WebSocketDisconnect:
        log.info("🔌 ESP32 ngắt")
    except Exception as e:
        log.exception(f"❌ ESP32 WS lỗi: {e}")
    finally:
        if transport is not None:
            transport._connected = False
        for t in (process_task, bootstrap_task):
            if t and not t.done():
                t.cancel()
        if handler is not None:
            try:
                await handler.abort()
            except Exception:
                pass
        hub.unregister_esp32(device_id, handler)
        hub.unregister_active_device(device_id)
        try:
            hub.online_devices()
            if not hub.is_online(device_id):
                await hub.broadcast_sync(device_id, "device_status", {"online": False})
        except Exception:
            pass
        try:
            get_device_mcp_manager().detach(device_id, channel="audio", transport=transport)
        except Exception:
            pass
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception:
                pass
        log.info(f"🔌 Session #{session_id} đóng")


async def _process_vad_audio(handler, session_id, log, pcm):
    try:
        t0 = time.perf_counter()
        wav = _pcm_to_wav(pcm)
        turn_id = uuid.uuid4().hex[:8]
        user_text = await handler.handle_voice_wav(wav)
        log.info(f"✅ Pipeline [{(time.perf_counter()-t0)*1000:.0f}ms] | user='{user_text}'")
        if user_text:
            await handler.wait_for_quick_audio()
            await handler.flush_pending_music()
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.save_message(
                        db, session_id, "user", user_text,
                        audio_bytes=handler.get_captured("user_wav"), audio_ext="wav", turn_id=turn_id)
                    bot_msg = handler.dialogue.last_assistant()
                    if bot_msg and bot_msg.content:
                        await chat_service.save_message(
                            db, session_id, "assistant",
                            bot_msg.content,
                            audio_bytes=handler.get_captured("bot_mp3"), audio_ext="mp3", turn_id=turn_id)
                        handler._captured["bot_mp3_parts"] = []
            except Exception as e:
                log.warning(f"⚠️ Lưu audio DB: {e}")
            if handler._close_after_end:
                handler._close_after_end = False
                await handler._send_callback({"type": "goodbye"})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception(f"❌ Xử lý VAD lỗi: {e}")
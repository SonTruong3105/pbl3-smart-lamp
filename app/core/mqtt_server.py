"""MQTT Broker adapter — bridge MQTT messages ↔ ConnectionHandler.

Windows note:
    Uvicorn trên Windows dùng ProactorEventLoop.
    aiomqtt/paho cần add_reader → NotImplementedError trên Proactor.
    → Chạy MQTT client trong thread riêng với SelectorEventLoop.
    → Forward messages sang main loop qua run_coroutine_threadsafe.
"""
import asyncio
import json
import sys
import threading
from typing import Optional, Dict
import aiomqtt
from loguru import logger
from app.config import config
from app.core.utils.udp_crypto import UdpCrypto, generate_key_nonce

class MqttBroker:
    """
    MQTT client chạy trong thread riêng với SelectorEventLoop.
    """

    def __init__(self):
        self.host = config.mqtt_broker_host
        self.port = config.mqtt_broker_port
        self.username = config.mqtt_username
        self.password = config.mqtt_password

        self._client: Optional[aiomqtt.Client] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._mqtt_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._on_message = None
        self._ready = threading.Event()

    def set_message_handler(self, handler):
        self._on_message = handler

    async def start(self):
        if not config.mqtt_enabled:
            logger.info("📡 MQTT disabled")
            return

        logger.info(f"📡 MQTT client → {self.host}:{self.port}")

        # Lưu main loop (uvicorn loop) — chạy trong main thread
        self._main_loop = asyncio.get_running_loop()

        # Khởi động MQTT thread
        self._thread = threading.Thread(
            target=self._run_thread,
            daemon=True,
            name="mqtt-broker",
        )
        self._thread.start()

        # Chờ MQTT thread ready (tối đa 5s)
        ready = await self._main_loop.run_in_executor(
            None, self._ready.wait, 5.0
        )
        if not ready:
            logger.warning("⚠️ MQTT thread không ready sau 5s")
        else:
            logger.info("📡 MQTT broker thread ready")

    def _run_thread(self):
        """Entry point của MQTT thread."""
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(
                asyncio.WindowsSelectorEventLoopPolicy()
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._mqtt_loop = loop

        self._ready.set()

        try:
            loop.run_until_complete(self._run_forever())
        except Exception as e:
            logger.exception(f"❌ MQTT thread crash: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._mqtt_loop = None

    async def _run_forever(self):
        """Loop chính của MQTT client — chạy trong MQTT thread."""
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ MQTT lỗi: {e} — reconnect 5s")
                await asyncio.sleep(5)

    # ============ SAFE HANDLER — bắt exception ============
    async def _safe_handler(self, msg):
        """Wrapper có log lỗi — tránh exception bị nuốt vào Future."""
        try:
            await self._on_message(msg)
        except Exception as e:
            logger.exception(f"❌ MQTT handler crash: {e}")

    async def _connect_and_listen(self):
        """Kết nối broker và lắng nghe messages."""
        kwargs = {"hostname": self.host, "port": self.port}
        if self.username:
            kwargs["username"] = self.username
        if self.password:
            kwargs["password"] = self.password

        async with aiomqtt.Client(**kwargs) as client:
            self._client = client
            logger.info("✅ MQTT connected")
            await client.subscribe("xiaozhi/+/up")
            logger.info("📡 Subscribed: xiaozhi/+/up")

            async for msg in client.messages:
                if not self._on_message or not self._main_loop:
                    continue

                # ✅ Forward sang main loop + log exception nếu có
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._safe_handler(msg),
                        self._main_loop,
                    )
                    future.add_done_callback(self._on_future_done)
                except Exception as e:
                    logger.exception(f"❌ MQTT forward lỗi: {e}")

    @staticmethod
    def _on_future_done(fut):
        """Log exception từ coroutine chạy trên main loop."""
        try:
            fut.result()
        except Exception as e:
            logger.exception(f"❌ MQTT future exception: {e}")

    async def publish(self, topic: str, payload: str):
        """Publish — tự động forward sang MQTT thread nếu cần."""
        if not self._client or not self._mqtt_loop:
            logger.warning("⚠️ MQTT chưa connect")
            return

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        try:
            if current is self._mqtt_loop:
                # Đang trong MQTT thread → publish trực tiếp
                await self._client.publish(topic, payload)
            else:
                # Đang ở main loop → forward sang MQTT thread
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.publish(topic, payload),
                    self._mqtt_loop,
                )
                await asyncio.wrap_future(fut)
        except Exception as e:
            logger.warning(f"⚠️ MQTT publish lỗi: {e}")

    async def stop(self):
        if self._thread and self._thread.is_alive():
            logger.info("🛑 Stopping MQTT broker...")
            if self._mqtt_loop and self._mqtt_loop.is_running():
                self._mqtt_loop.call_soon_threadsafe(self._mqtt_loop.stop)
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._thread.join, 3.0
                )
            except Exception:
                pass

class MqttConnectionManager:
    def __init__(self):
        self.broker = MqttBroker()
        self.sessions: Dict[str, dict] = {}
        self.nonce_to_device: Dict[str, str] = {}

    async def start(self):
        if not config.mqtt_enabled:
            return
        self.broker.set_message_handler(self._on_mqtt_message)
        await self.broker.start()
        from app.core.udp_server import get_udp_server
        udp = get_udp_server()
        udp.set_audio_handler(self._on_udp_audio)
        await udp.start()

    async def stop(self):
        await self.broker.stop()
        from app.core.udp_server import get_udp_server
        await get_udp_server().stop()

    async def _on_mqtt_message(self, msg):
        """Entry point — được gọi từ MQTT thread qua forward."""
        try:
            topic = str(msg.topic)
            parts = topic.split("/")
            if len(parts) < 3:
                logger.warning(f"⚠️ Topic sai format: {topic}")
                return
            device_id = parts[1]

            try:
                data = json.loads(msg.payload.decode("utf-8"))
            except Exception as e:
                logger.warning(f"⚠️ Payload không phải JSON: {e}")
                return

            msg_type = data.get("type")
            logger.debug(f"📨 MQTT [{device_id}] type={msg_type}")

            if msg_type == "hello":
                await self._handle_hello(device_id, data)
            elif msg_type == "sensor_data":
                from app.core.providers.tools import sensor_state
                sensor_state.update_bulk({
                    "temperature": data.get("temperature"),
                    "humidity": data.get("humidity"),
                    "air_quality_ppm": data.get("air_quality_ppm"),
                    "light_lux": data.get("light_lux"),
                    "presence": data.get("presence"),
                })
                logger.info(f"📊 Sensor updated từ {device_id}: {data}")
            elif msg_type == "mcp":
                payload = data.get("payload", {})
                logger.info(f"📥 MCP reply từ {device_id}: {str(payload)[:200]}")
                s = self.sessions.get(device_id)
                if s and "_mcp_future" in s:
                    fut = s["_mcp_future"]
                    if not fut.done():
                        fut.set_result(payload)
            elif msg_type == "mcp_reply":
                logger.info(
                    f"📥 MCP reply (legacy) từ {device_id}: "
                    f"{data.get('method')} → {data.get('result')}"
                )
                s = self.sessions.get(device_id)
                if s and "_mcp_future" in s:
                    fut = s["_mcp_future"]
                    if not fut.done():
                        fut.set_result({"result": data.get("result")})

            elif device_id in self.sessions:
                await self._handle_control(device_id, data)
            else:
                logger.debug(f"📨 Bỏ qua (chưa hello): {msg_type}")
        except Exception as e:
            logger.exception(f"❌ _on_mqtt_message crash: {e}")
            raise

    async def _handle_hello(self, device_id: str, data: dict):
        """Xử lý hello — có log từng bước để debug."""
        from app.core.logger import get_session_logger

        log = get_session_logger(None, device_id)
        log.info(f"🔌 MQTT hello từ {device_id}")

        try:
            log.debug("[1/6] Import các module cần thiết")
            from app.core.esp32_connection import ESP32ConnectionHandler
            from app.core.protocols import MqttTransport
            from app.core.utils.opus_codec import OpusCodec
            from app.core.providers.vad.energy import EnergyVAD
            from app.core.providers.vad.silero import SileroVAD
            
            from app.database import AsyncSessionLocal
            from app.services import chat as chat_service
            from app.config import config as _cfg
        except Exception as e:
            log.exception(f"❌ Import fail: {e}")
            raise

        try:
            log.debug("[2/6] Tạo session trong DB")
            async with AsyncSessionLocal() as db:
                await chat_service.get_or_create_device(db, device_id, "esp32")
                session, is_new = await chat_service.resume_or_create_session(
                    db, device_id, None,
                )
                session_id = session.id
        except Exception as e:
            log.exception(f"❌ Tạo session fail: {e}")
            raise

        log = get_session_logger(session_id, device_id)
        log.debug(f"[3/6] Session #{session_id} (new={is_new})")

        try:
            log.debug("[4/6] Sinh AES key/nonce + tạo transport + handler")
            aes_key_hex, aes_nonce_hex = generate_key_nonce()
            crypto = UdpCrypto(aes_key_hex, aes_nonce_hex)
            log.info(f"🔑 Sinh key/nonce | key={aes_key_hex[:8]}... nonce={aes_nonce_hex[:8]}...")

            transport = MqttTransport(
                device_id=device_id,
                broker=self.broker,
                crypto=crypto,
            )
            handler = ESP32ConnectionHandler(transport, session_id, device_id)
        except Exception as e:
            log.exception(f"❌ Tạo handler fail: {e}")
            raise

        try:
            log.debug("[5/6] Tạo VAD + Opus codec")
            vad_cfg = _cfg.vad_config
            vad_type = _cfg.vad_provider  # "energy" hoặc "silero"

            if vad_type == "silero":
                model_dir = vad_cfg.get("model_dir", "models/snakers4_silero-vad")
                vad = SileroVAD(
                    model_path=f"{model_dir}/silero_vad.onnx",
                    sample_rate=16000,
                    threshold=vad_cfg.get("threshold", 0.5),
                    threshold_low=vad_cfg.get("threshold_low", 0.2),
                    silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
                    min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
                )
                log.info(f"🎤 Dùng SileroVAD | threshold={vad.threshold}")
            else:
                vad = EnergyVAD(
                    sample_rate=16000,
                    frame_duration_ms=60,
                    silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
                    min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
                    energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
                    initial_threshold=vad_cfg.get("initial_threshold", 500.0),
                    hangover_ms=vad_cfg.get("hangover_ms", 200),
                    pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
                    post_speech_ms=vad_cfg.get("post_speech_ms", 300),
                )
                log.info(f"🎤 Dùng EnergyVAD | threshold={vad.threshold:.0f}")
            opus = OpusCodec(sample_rate=16000, channels=1)
        except Exception as e:
            log.exception(f"❌ Tạo VAD/Opus fail: {e}")
            raise

        self.sessions[device_id] = {
            "session_id": session_id,
            "handler": handler,
            "transport": transport,
            "vad": vad,
            "opus": opus,
            "crypto": crypto,
            "aes_nonce_hex": aes_nonce_hex,
            "udp_addr": None,
            "log": log,
            "process_task": None,
            "listen_mode": "auto",
        }
        # ✅ Đăng ký nonce -> device_id để định tuyến UDP
        self.nonce_to_device[aes_nonce_hex] = device_id

        try:
            log.debug("[6/6] Gửi hello response")
            await transport.send_json({
                "type": "hello",
                "version": 3,
                "session_id": str(session_id),
                "transport": "udp",
                "udp": {
                    "server": _cfg.udp_endpoint,
                    "port": _cfg.udp_port,
                    "key": aes_key_hex,
                    "nonce": aes_nonce_hex,
                },
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            })
        except Exception as e:
            log.exception(f"❌ Gửi hello response fail: {e}")
            raise

        log.info(f"✅ MQTT session #{session_id} ready")

    async def _handle_control(self, device_id: str, data: dict):
        s = self.sessions.get(device_id)
        if not s:
            return
        log = s["log"]
        msg_type = data.get("type")

        if msg_type == "listen":
            mode = (data.get("mode") or "auto").lower()
            state = (data.get("state") or "").lower()
            s["listen_mode"] = mode

            if state == "start":
                log.info(f"🎤 Listen START | mode={mode}")
                s["vad"].reset()
                s["_manual_pcm"] = []
                s["_listening"] = True

            elif state == "stop":
                log.info(f"🎤 Listen STOP | mode={mode}")
                s["_listening"] = False

                if mode == "manual":
                    pcm_chunks = s.get("_manual_pcm", [])
                    if pcm_chunks:
                        pcm = b"".join(pcm_chunks)
                        log.info(f"📦 Manual: {len(pcm)}b PCM → ASR")
                        task = s.get("process_task")
                        if task is None or task.done():
                            s["process_task"] = asyncio.create_task(
                                self._process_pcm(s, pcm)
                            )
                    s["_manual_pcm"] = []

            elif state == "detect":
                log.info(f"🎤 Listen DETECT | mode={mode}")
                s["vad"].reset()

            else:
                log.info(f"🎤 Listen mode={mode} (no state)")
                s["vad"].reset()

        elif msg_type == "abort":
            task = s.get("process_task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except Exception:
                    pass
                s["process_task"] = None
            s["handler"].abort()
            s["vad"].reset()
            s["_manual_pcm"] = []
            s["_listening"] = False
            log.info("⏹️ Abort")

        elif msg_type == "goodbye":
            await self._close_session(device_id)

    async def _on_udp_audio(self, data: bytes, addr: tuple):
        # Packet: [16b header][encrypted] — KHÔNG có nonce
        if len(data) < 16:
            logger.warning(f"⚠️ UDP packet quá ngắn: {len(data)}b")
            return

        # 1. Tìm session đã bind với addr này
        for device_id, s in self.sessions.items():
            if s["udp_addr"] == addr:
                await self._process_udp(device_id, s, data)
                return

        # 2. Chưa bind → bind vào session đang chờ
        for device_id, s in self.sessions.items():
            if s["udp_addr"] is None:
                s["udp_addr"] = addr
                if hasattr(s["transport"], "udp_addr"):
                    s["transport"].udp_addr = addr
                s["log"].info(f"📡 UDP bound: {addr}")
                await self._process_udp(device_id, s, data)
                return

        logger.debug(f"⚠️ UDP từ addr lạ: {addr}")

    async def _process_udp(self, device_id: str, s: dict, packet: bytes):
        log = s["log"]

        err_count = s.get("udp_err_count", 0)
        if len(packet) < 16:
            return

        import struct

        # ✅ 16 byte đầu tiên CHÍNH LÀ NONCE
        packet_nonce = packet[:16]
        encrypted = packet[16:]

        if not encrypted:
            return

        # Parse metadata để debug
        type_ = packet_nonce[0]
        seq = struct.unpack(">I", packet_nonce[12:16])[0]

        # ✅ Giải mã với nonce ĐẦY ĐỦ từ gói
        try:
            opus_frame = s["crypto"].decrypt_with_packet_nonce(encrypted, packet_nonce)
        except Exception as e:
            if err_count < 3: log.warning(f"⚠️ AES decrypt: {e}")
            s["udp_err_count"] = err_count + 1
            return

        if not opus_frame:
            return

        # ✅ Bước 2: Opus decode -> PCM
        try:
            pcm = s["opus"].decode(opus_frame)
        except Exception as e:
            log.warning(f"⚠️ Opus decode: {e}")
            return

        mode = s.get("listen_mode", "auto")

        if mode == "manual":
            # Manual: tích lũy PCM chờ state=stop
            s.setdefault("_manual_pcm", []).append(pcm)
            if len(s["_manual_pcm"]) > 500:
                s["_manual_pcm"] = s["_manual_pcm"][-500:]
            return

        # Auto mode: VAD detect end-of-speech
        is_end = s["vad"].push(pcm)
        if is_end:
            pcm_data = s["vad"].get_audio()
            s["vad"].reset()
            task = s.get("process_task")
            if pcm_data and (task is None or task.done()):
                s["process_task"] = asyncio.create_task(
                    self._process_pcm(s, pcm_data)
                )

    async def _process_pcm(self, s: dict, pcm: bytes):
        import io, wave
        log = s["log"]
        handler = s["handler"]
        session_id = s["session_id"]

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm)
        wav = buf.getvalue()

        try:
            user_text = await handler.handle_voice_wav(wav)
            log.info(f"✅ Pipeline | user='{user_text}'")

            from app.database import AsyncSessionLocal
            from app.services import chat as chat_service

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
            raise
        except Exception as e:
            log.exception(f"❌ Pipeline: {e}")

    async def _close_session(self, device_id: str):
        s = self.sessions.pop(device_id, None)
        if not s:
            return

        # ✅ Xóa ánh xạ nonce -> device_id
        nonce = s.get("aes_nonce_hex")
        if nonce:
            self.nonce_to_device.pop(nonce, None)

        task = s.get("process_task")
        if task and not task.done():
            task.cancel()

        from app.database import AsyncSessionLocal
        from app.services import chat as chat_service

        try:
            async with AsyncSessionLocal() as db:
                await chat_service.close_session(db, s["session_id"])
        except Exception:
            pass

_manager: Optional[MqttConnectionManager] = None

def get_mqtt_manager() -> MqttConnectionManager:
    global _manager
    if _manager is None:
        _manager = MqttConnectionManager()
    return _manager
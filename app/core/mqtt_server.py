"""MQTT Broker + Gateway — hỗ trợ giao thức MQTT + UDP của ESP32 Xiaozhi."""
import asyncio
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger

from app.config import config
from app.core.device_auth import verify_device_token
from app.core.device_hub import get_device_hub
from app.core.esp32_connection import ESP32ConnectionHandler
from app.core.logger import get_session_logger
from app.core.protocols import MqttUdpTransport
from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
from app.core.udp_server import get_udp_server
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.udp_crypto import UdpCrypto, generate_key_nonce
from app.database import AsyncSessionLocal
from app.repositories import chat as chat_service
from app.routes.esp32_ws import (
    _broadcast_esp_state_to_web,
    _extract_mcp_json_result,
    _make_denoiser,
    _make_vad,
    _process_vad_audio,
    _respond_wake_word,
)

try:
    from amqtt.broker import Broker
    HAS_AMQTT = True
except ImportError:
    HAS_AMQTT = False


def _sanitize_topic(mac: str) -> str:
    return mac.replace(":", "_").lower()


def _un_sanitize(s: str) -> str:
    return s.replace("_", ":").upper()


@dataclass
class MqttSession:
    session_id: str
    db_session_id: int
    device_id: str
    client_id: str
    pub_topic: str
    sub_topic: str
    aes_key: str
    aes_nonce: str
    crypto: UdpCrypto
    opus: OpusCodec = field(default_factory=lambda: OpusCodec(sample_rate=16000, channels=1))
    vad: object = field(default_factory=_make_vad)
    denoiser: object = None
    udp_addr: Optional[tuple] = None
    handler: Optional[ESP32ConnectionHandler] = None
    transport: Optional[MqttUdpTransport] = None
    process_task: Optional[asyncio.Task] = None
    listen_mode: str = "auto"
    local_seq: int = 0
    remote_seq: int = 0
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class MqttManager:
    def __init__(self):
        self.broker = None
        self.sessions: Dict[str, MqttSession] = {}
        self.nonce_to_session: Dict[bytes, MqttSession] = {}
        self.device_to_session: Dict[str, MqttSession] = {}
        self.control_devices: Dict[str, dict] = {}
        self._running = False
        self._internal_client = None

    async def start(self):
        if not config.mqtt_enabled:
            logger.info("📡 MQTT disabled")
            return
        if not HAS_AMQTT:
            logger.warning("⚠️ amqtt chưa cài — pip install amqtt")
            return

        broker_cfg = {
            "listeners": {
                "default": {
                    "type": "tcp",
                    "bind": f"{config.mqtt_host}:{config.mqtt_port}",
                }
            },
            "sys_interval": 0,
            "auth": {
                "allow-anonymous": True,
                "plugins": ["auth_anonymous"],
            },
            "topic-check": {
                "enabled": False,
            },
        }
        self.broker = Broker(broker_cfg)
        await self.broker.start()
        self._running = True
        logger.info(f"📡 MQTT broker → {config.mqtt_host}:{config.mqtt_port}")

        udp = get_udp_server()
        udp.set_audio_handler(self._on_udp_packet)
        await udp.start()

        asyncio.create_task(self._gateway_client())
        asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        self._running = False
        for s in list(self.sessions.values()):
            await self._close_session(s.session_id)
        try:
            await get_udp_server().stop()
        except Exception:
            pass
        if self.broker:
            try:
                await self.broker.shutdown()
            except Exception:
                pass

    async def _gateway_client(self):
        from amqtt.client import MQTTClient
        await asyncio.sleep(0.5)
        client = MQTTClient(client_id="xiaozhi-server-gateway")
        self._internal_client = client
        try:
            await client.connect(f"mqtt://127.0.0.1:{config.mqtt_port}/")
            await client.subscribe([
                ("devices/p2p/#", 0),
                ("devices/control/#", 0),
                ("devices/status/#", 0),
            ])
            logger.info("📡 MQTT gateway subscribed: devices/p2p/#, devices/control/#, devices/status/#")

            while self._running:
                try:
                    msg = await client.deliver_message(timeout=1.0)
                    if msg is None:
                        continue
                    topic = msg.topic
                    payload = msg.publish_packet.payload.data
                    await self._handle_mqtt_message(topic, payload)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if self._running:
                        logger.warning(f"⚠️ MQTT gateway msg error: {e}")
        except Exception as e:
            logger.error(f"❌ MQTT gateway lỗi: {e}")

    async def _publish(self, topic: str, data: dict):
        if not self._internal_client:
            return
        try:
            await self._internal_client.publish(
                topic, json.dumps(data, ensure_ascii=False).encode("utf-8"), qos=0
            )
        except Exception as e:
            logger.warning(f"⚠️ MQTT publish {topic}: {e}")

    async def _handle_mqtt_message(self, topic: str, raw: bytes):
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return

        msg_type = data.get("type")

        # ── Persistent control channel ──
        if topic.startswith("devices/control/"):
            parts = topic.split("/")
            if len(parts) < 4:
                return
            direction = parts[2]
            sanitized_id = parts[3]
            if direction != "up":
                return
            device_id = data.get("device_id") or _un_sanitize(sanitized_id)

            if msg_type == "register":
                if config.auth_enabled and not verify_device_token(device_id, data.get("token", "")):
                    logger.warning(f"🚫 MQTT control auth fail: {device_id}")
                    return
                down_topic = f"devices/control/down/{sanitized_id}"
                self.control_devices[device_id] = {
                    "down_topic": down_topic,
                    "last_seen": time.time(),
                    "online": True,
                }
                hub = get_device_hub()
                hub.register_active_device(device_id)
                transport = MqttUdpTransport(
                    publish_fn=self._publish,
                    pub_topic=down_topic,
                    send_udp_fn=None,
                    session_id=f"ctrl-{sanitized_id}",
                )
                get_device_mcp_manager().attach(device_id, transport, channel="control")
                await self._publish(down_topic, {
                    "type": "register_ack",
                    "device_id": device_id,
                    "status": "ok",
                })
                await hub.broadcast_sync(device_id, "device_status", {"online": True})
                logger.info(f"📡 MQTT control registered: {device_id}")
                asyncio.create_task(self._discover_control_tools(device_id))

            elif msg_type == "heartbeat":
                if device_id in self.control_devices:
                    self.control_devices[device_id]["last_seen"] = time.time()
                    self.control_devices[device_id]["online"] = True
                get_device_hub().register_active_device(device_id)

            elif msg_type == "mcp":
                if device_id in self.control_devices:
                    self.control_devices[device_id]["last_seen"] = time.time()
                payload = data.get("payload", {})
                if isinstance(payload, dict):
                    get_device_mcp_manager().handle_mcp_message(device_id, payload)
                    res = payload.get("result")
                    if isinstance(res, dict) and res.get("tools") is not None:
                        await get_device_mcp_manager().register_device_tools(
                            device_id, res["tools"]
                        )
                    parsed_res = _extract_mcp_json_result(payload)
                    if parsed_res:
                        asyncio.create_task(_broadcast_esp_state_to_web(device_id, parsed_res))
            return

        # ── Device status (LWT / online) ──
        if topic.startswith("devices/status/"):
            parts = topic.split("/")
            if len(parts) < 3:
                return
            device_id = _un_sanitize(parts[2])
            online = bool(data.get("online", False))
            if not online:
                self.control_devices.pop(device_id, None)
                get_device_hub().unregister_active_device(device_id)
                get_device_mcp_manager().detach(device_id, channel="control")
                await get_device_hub().broadcast_sync(device_id, "device_status", {"online": False})
                logger.info(f"📡 MQTT device offline (LWT): {device_id}")
            return

        if not topic.startswith("devices/p2p/"):
            return

        parts = topic.split("/")
        if len(parts) < 4:
            return
        client_id = parts[2]
        device_topic_id = parts[3]

        if msg_type == "hello":
            await self._on_hello(client_id, device_topic_id, data)
            return

        sid = data.get("session_id")
        session = self.sessions.get(sid) if sid else None
        if not session:
            device_id = _un_sanitize(device_topic_id)
            session = self.device_to_session.get(device_id)
        if not session:
            return

        session.last_active = time.time()
        log = get_session_logger(session.db_session_id, session.device_id)

        if msg_type == "listen":
            session.listen_mode = (data.get("mode") or "auto").lower()
            state = (data.get("state") or "").lower()
            if state == "detect":
                session.vad.reset()
                if session.denoiser is not None:
                    session.denoiser.reset()
                if config._get("wake_word", "enabled", default=False) and session.handler:
                    await _respond_wake_word(session.handler, log)
                    session.vad.reset()
                    if session.denoiser is not None:
                        session.denoiser.reset()
            elif state == "start":
                session.vad.reset()
                if session.denoiser is not None:
                    session.denoiser.reset()
            elif state == "stop" and session.listen_mode == "manual":
                if session.vad.has_speech():
                    pcm = session.vad.get_audio()
                    session.vad.reset()
                    if session.denoiser is not None:
                        session.denoiser.reset()
                    if pcm and (session.process_task is None or session.process_task.done()):
                        session.process_task = asyncio.create_task(
                            _process_vad_audio(session.handler, session.db_session_id, log, pcm)
                        )

        elif msg_type == "abort":
            if session.process_task and not session.process_task.done():
                session.process_task.cancel()
            if session.handler:
                await session.handler.abort()
            session.vad.reset()
            if session.denoiser is not None:
                session.denoiser.reset()

        elif msg_type == "goodbye":
            await self._close_session(session.session_id)

        elif msg_type == "mcp":
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                return
            method = payload.get("method")
            req_id = payload.get("id")
            mcp_mgr = get_device_mcp_manager()

            if "result" in payload or "error" in payload:
                mcp_mgr.handle_mcp_message(session.device_id, payload)
                res = payload.get("result")
                if isinstance(res, dict) and res.get("tools") is not None:
                    await mcp_mgr.register_device_tools(session.device_id, res["tools"])
                parsed_res = _extract_mcp_json_result(payload)
                if parsed_res:
                    asyncio.create_task(_broadcast_esp_state_to_web(session.device_id, parsed_res))
            elif method == "initialize":
                await session.transport.send_json({
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "xiaozhi-ce", "version": "2.0.0"},
                        },
                    },
                })
            elif method == "tools/list":
                tl = payload.get("params", {}).get("tools") or payload.get("result", {}).get("tools", [])
                if tl:
                    await mcp_mgr.register_device_tools(session.device_id, tl)
                await session.transport.send_json({
                    "type": "mcp",
                    "payload": {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tl}},
                })

    async def _discover_control_tools(self, device_id: str):
        try:
            await asyncio.sleep(0.5)
            await get_device_mcp_manager().discover_tools(device_id)
        except Exception as e:
            logger.debug(f"Discover control tools {device_id}: {e}")

    async def _on_hello(self, client_id: str, device_topic_id: str, data: dict):
        device_id = data.get("device_id") or _un_sanitize(device_topic_id)
        if config.auth_enabled and not verify_device_token(device_id, data.get("token", "")):
            logger.warning(f"🚫 MQTT hello auth fail: {device_id}")
            return

        old = self.device_to_session.get(device_id)
        if old:
            await self._close_session(old.session_id)

        sid = secrets.token_hex(4)
        key_hex, nonce_hex = generate_key_nonce()
        crypto = UdpCrypto(key_hex, nonce_hex)
        nonce_bytes = bytes.fromhex(nonce_hex)

        async with AsyncSessionLocal() as db:
            await chat_service.get_or_create_device(db, device_id, "esp32")
            db_sess, _ = await chat_service.resume_or_create_session(db, device_id, None)
            db_session_id = db_sess.id

        log = get_session_logger(db_session_id, device_id)
        pub_topic = f"devices/p2p/{device_topic_id}/{client_id}"
        sub_topic = f"devices/p2p/{client_id}/{device_topic_id}"

        session = MqttSession(
            session_id=sid,
            db_session_id=db_session_id,
            device_id=device_id,
            client_id=client_id,
            pub_topic=pub_topic,
            sub_topic=sub_topic,
            aes_key=key_hex,
            aes_nonce=nonce_hex,
            crypto=crypto,
            denoiser=_make_denoiser(log),
        )

        async def _send_udp(opus_bytes: bytes):
            if not session.udp_addr:
                return
            session.local_seq += 1
            header = bytearray(16)
            header[0] = 0x01
            header[2:4] = len(opus_bytes).to_bytes(2, "big")
            header[4:8] = int(time.time()).to_bytes(4, "big")
            header[8:12] = session.local_seq.to_bytes(4, "big")
            header[12:16] = len(opus_bytes).to_bytes(4, "big")
            pkt_nonce = bytes(header)
            encrypted = crypto.encrypt_with_packet_nonce(opus_bytes, pkt_nonce)
            await get_udp_server().send_audio(session.udp_addr, pkt_nonce + encrypted)

        transport = MqttUdpTransport(
            publish_fn=self._publish,
            pub_topic=pub_topic,
            send_udp_fn=_send_udp,
            session_id=sid,
        )
        handler = ESP32ConnectionHandler(transport, db_session_id, device_id)
        session.transport = transport
        session.handler = handler

        self.sessions[sid] = session
        self.nonce_to_session[nonce_bytes[:4]] = session
        self.device_to_session[device_id] = session

        hub = get_device_hub()
        hub.register_esp32(device_id, handler)
        hub.register_active_device(device_id)
        get_device_mcp_manager().attach(device_id, transport, channel="audio")

        public_host = os.environ.get("PUBLIC_UDP_HOST") or config.udp_public_host or config.host
        if public_host in ("0.0.0.0", ""):
            public_host = "127.0.0.1"

        await self._publish(pub_topic, {
            "type": "hello",
            "version": 3,
            "session_id": sid,
            "transport": "udp",
            "udp": {
                "server": public_host,
                "port": config.udp_port,
                "encryption": "aes-128-ctr",
                "key": key_hex,
                "nonce": nonce_hex,
            },
            "audio_params": {
                "format": "opus",
                "sample_rate": config.sample_rate,
                "channels": 1,
                "frame_duration": 60,
            },
        })
        log.info(f"📡 MQTT hello OK | sid={sid} | udp={public_host}:{config.udp_port}")

    async def _on_udp_packet(self, data: bytes, addr: tuple):
        if len(data) < 16:
            return
        pkt_nonce = data[:16]
        encrypted = data[16:]

        session = self.nonce_to_session.get(pkt_nonce[:4])
        if not session:
            for s in list(self.sessions.values()):
                if s.udp_addr == addr:
                    session = s
                    break
        if not session:
            return

        session.udp_addr = addr
        session.last_active = time.time()

        try:
            opus_frame = session.crypto.decrypt_with_packet_nonce(encrypted, pkt_nonce)
        except Exception:
            return
        if not opus_frame:
            return

        try:
            pcm = session.opus.decode(opus_frame)
            if session.denoiser is not None and pcm:
                pcm = await asyncio.to_thread(session.denoiser.process_pcm16_16k, pcm)
                if not pcm:
                    return
        except Exception:
            return

        if session.vad.push(pcm):
            log = get_session_logger(session.db_session_id, session.device_id)
            pcm_data = session.vad.get_audio()
            session.vad.reset()
            if session.denoiser is not None:
                session.denoiser.reset()
            if pcm_data and (session.process_task is None or session.process_task.done()):
                session.process_task = asyncio.create_task(
                    _process_vad_audio(session.handler, session.db_session_id, log, pcm_data)
                )

    async def _close_session(self, sid: str):
        session = self.sessions.pop(sid, None)
        if not session:
            return
        for k, v in list(self.nonce_to_session.items()):
            if v is session:
                self.nonce_to_session.pop(k, None)
        if self.device_to_session.get(session.device_id) is session:
            self.device_to_session.pop(session.device_id, None)

        if session.process_task and not session.process_task.done():
            session.process_task.cancel()
        if session.handler:
            try:
                await session.handler.abort()
            except Exception:
                pass
        hub = get_device_hub()
        hub.unregister_esp32(session.device_id, session.handler)
        if session.device_id not in self.control_devices:
            hub.unregister_active_device(session.device_id)
        get_device_mcp_manager().detach(
            session.device_id, channel="audio", transport=session.transport
        )
        try:
            async with AsyncSessionLocal() as db:
                await chat_service.close_session(db, session.db_session_id)
        except Exception:
            pass

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(30)
            now = time.time()
            for sid, s in list(self.sessions.items()):
                if now - s.last_active > 300:
                    await self._close_session(sid)
            for did, info in list(self.control_devices.items()):
                if now - info.get("last_seen", 0) > 120:
                    self.control_devices.pop(did, None)
                    get_device_hub().unregister_active_device(did)
                    get_device_mcp_manager().detach(did, channel="control")
                    await get_device_hub().broadcast_sync(did, "device_status", {"online": False})


_mqtt: Optional[MqttManager] = None


def get_mqtt_manager() -> MqttManager:
    global _mqtt
    if _mqtt is None:
        _mqtt = MqttManager()
    return _mqtt
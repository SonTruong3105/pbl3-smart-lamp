"""UDP Audio server — nhận/gửi Opus frames qua UDP."""
import asyncio
from typing import Optional, Callable, Tuple
from loguru import logger
from app.config import config


class UdpAudioServer:
    def __init__(self):
        self.host = config.udp_host
        self.port = config.udp_port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._on_audio: Optional[Callable] = None

    def set_audio_handler(self, handler):
        self._on_audio = handler

    async def start(self):
        if not config.mqtt_enabled:
            logger.info("📡 UDP disabled")
            return
        loop = asyncio.get_event_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._on_audio),
            local_addr=(self.host, self.port),
        )
        logger.info(f"📡 UDP server → {self.host}:{self.port}")

    async def stop(self):
        if self._transport:
            self._transport.close()

    async def send_audio(self, addr: Tuple[str, int], data: bytes, codec=None):
        if self._transport:
            self._transport.sendto(data, addr)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_audio=None):
        self.transport = None
        self.on_audio = on_audio

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        if self.on_audio:
            try:
                asyncio.create_task(self.on_audio(data, addr))
            except Exception as e:
                logger.warning(f"⚠️ UDP handler: {e}")

    def error_received(self, exc):
        logger.warning(f"⚠️ UDP error: {exc}")


_udp: Optional[UdpAudioServer] = None


def get_udp_server() -> UdpAudioServer:
    global _udp
    if _udp is None:
        _udp = UdpAudioServer()
    return _udp

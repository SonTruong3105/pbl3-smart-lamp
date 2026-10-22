"""Transport abstraction — WebSocket vs MQTT+UDP."""
from abc import ABC, abstractmethod
import asyncio


class Transport(ABC):
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    async def send_json(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_audio(self, audio: bytes) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class WebSocketTransport(Transport):
    """WS transport có timeout — tránh treo khi ESP32 không đọc."""

    SEND_TIMEOUT = 10.0

    def __init__(self, ws):
        self.ws = ws
        self._connected = True

    @property
    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            return self.ws.client_state.name == "CONNECTED"
        except Exception:
            return False

    async def send_json(self, payload: dict) -> None:
        if not self._connected:
            raise ConnectionError("WS disconnected")
        try:
            await asyncio.wait_for(
                self.ws.send_json(payload),
                timeout=self.SEND_TIMEOUT,
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            self._connected = False
            raise ConnectionError(f"WS send_json dead: {e}")

    async def send_audio(self, audio: bytes) -> None:
        if not self._connected:
            raise ConnectionError("WS disconnected")
        try:
            await asyncio.wait_for(
                self.ws.send_bytes(audio),
                timeout=self.SEND_TIMEOUT,
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            self._connected = False
            raise ConnectionError(f"WS send_bytes dead: {e}")

    async def close(self) -> None:
        self._connected = False
        try:
            await asyncio.wait_for(self.ws.close(), timeout=3.0)
        except Exception:
            pass


class MqttTransport(Transport):
    def __init__(self, device_id: str, broker, crypto=None, udp_addr=None):
        self.device_id = device_id
        self.broker = broker
        self.crypto = crypto
        self.udp_addr = udp_addr
        self._seq = 1
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_json(self, payload: dict) -> None:
        if not self._connected:
            return
        import json
        topic = f"xiaozhi/{self.device_id}/down"
        await asyncio.wait_for(
            self.broker.publish(topic, json.dumps(payload)),
            timeout=10.0,
        )

    async def send_audio(self, opus_bytes: bytes) -> None:
        if not self._connected or not self.udp_addr or not self.crypto:
            return
        import time

        packet_nonce = bytearray(self.crypto.nonce)
        payload_len = len(opus_bytes)
        ts = int(time.time() * 1000) & 0xFFFFFFFF
        seq = self._seq & 0xFFFFFFFF

        packet_nonce[0] = 0x01
        packet_nonce[1] = 0x00
        packet_nonce[2:4] = payload_len.to_bytes(2, "big")
        packet_nonce[4:8] = (0).to_bytes(4, "big")
        packet_nonce[8:12] = ts.to_bytes(4, "big")
        packet_nonce[12:16] = seq.to_bytes(4, "big")

        encrypted = self.crypto.encrypt_with_packet_nonce(
            opus_bytes, bytes(packet_nonce)
        )
        packet = bytes(packet_nonce) + encrypted

        from app.core.udp_server import get_udp_server
        await asyncio.wait_for(
            get_udp_server().send_audio(self.udp_addr, packet),
            timeout=5.0,
        )
        self._seq += 1

    async def close(self) -> None:
        self._connected = False

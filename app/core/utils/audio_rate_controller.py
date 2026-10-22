"""
AudioRateController — gửi audio đúng nhịp 60ms/frame.
Đồng bộ với server gốc xinnan-tech/xiaozhi-esp32-server.

- 5 packet đầu gửi ngay (pre-buffer, giảm latency)
- Các packet sau gửi cách nhau đúng frame_duration (60ms)
- Tránh tràn UDP buffer của ESP32
"""
import asyncio
import time


class AudioRateController:
    """Gửi audio packets theo nhịp chính xác."""

    def __init__(
        self,
        send_fn,
        frame_duration_ms: int = 60,
        pre_buffer_count: int = 5,
    ):
        self._send_fn = send_fn
        self.frame_duration = frame_duration_ms
        self.pre_buffer_count = pre_buffer_count
        self._sent_count = 0
        self._start_time = None
        self._lock = asyncio.Lock()

    async def send(self, packet: bytes):
        async with self._lock:
            if self._start_time is None:
                self._start_time = time.perf_counter()
                self._sent_count = 0

            if self._sent_count < self.pre_buffer_count:
                self._sent_count += 1
                await self._send_fn(packet)
                return

            expected_ms = self._sent_count * self.frame_duration
            elapsed_ms = (time.perf_counter() - self._start_time) * 1000
            delay_ms = expected_ms - elapsed_ms

            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

            self._sent_count += 1
            await self._send_fn(packet)

    def reset(self):
        self._sent_count = 0
        self._start_time = None

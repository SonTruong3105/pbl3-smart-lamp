"""Audio rate controller — gửi audio đúng nhịp 60ms/frame."""
import asyncio
import time
from typing import Optional


class AudioRateController:
    def __init__(self, frame_duration_ms: int = 60, pre_buffer_count: int = 3):
        self.frame_duration_ms = frame_duration_ms
        self.pre_buffer_count = pre_buffer_count
        self._sent_count = 0
        self._start_time: Optional[float] = None

    def start(self):
        self._sent_count = 0
        self._start_time = time.perf_counter()

    async def wait_for_next(self):
        if self._sent_count < self.pre_buffer_count:
            self._sent_count += 1
            return
        expected_ms = self._sent_count * self.frame_duration_ms
        elapsed_ms = (time.perf_counter() - self._start_time) * 1000
        delay_ms = expected_ms - elapsed_ms
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        self._sent_count += 1

    def reset(self):
        self._sent_count = 0
        self._start_time = None

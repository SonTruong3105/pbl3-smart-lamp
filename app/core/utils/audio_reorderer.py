"""Gom audio theo index, gửi đúng thứ tự 1,2,3..."""
import asyncio


class _AudioReorderer:
    """Gom audio theo index, gửi ra đúng thứ tự 1, 2, 3...

    Việc gửi (ESP32 pace real-time 60ms/frame) chạy trong 1 sender task riêng
    để TTS của câu sau được tổng hợp trong lúc câu trước đang phát.
    """

    def __init__(self, send_fn, log):
        self._send = send_fn
        self._log = log
        self._next_idx = 1
        self._buf: dict = {}
        self._out: asyncio.Queue = asyncio.Queue()
        self._sender = None
        self.total_ref = {"n": 0}

    def start(self):
        if self._sender is None:
            self._sender = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            item = await self._out.get()
            if item is None:
                break
            i, sent, data = item
            try:
                await self._send({
                    "type": "audio",
                    "index": i,
                    "total": self.total_ref["n"],
                    "sentence": sent,
                    "data": data,
                })
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log.warning(f"Reorderer #{i}: {e}")

    def _drain(self):
        while self._next_idx in self._buf:
            item = self._buf.pop(self._next_idx)
            if item is not None:
                sent, data = item
                self._out.put_nowait((self._next_idx, sent, data))
            self._next_idx += 1

    async def push(self, idx: int, sentence: str, audio: bytes):
        self._buf[idx] = (sentence, audio)
        self._drain()

    async def skip(self, idx: int):
        self._buf[idx] = None
        self._drain()

    async def close(self, wait: bool = True):
        task = self._sender
        if task is None:
            return
        self._sender = None
        if wait:
            self._out.put_nowait(None)
            try:
                await asyncio.wait_for(task, timeout=15.0)
            except asyncio.CancelledError:
                task.cancel()
                raise
            except asyncio.TimeoutError:
                self._log.error("Audio sender timeout sau 15s -> huy")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except Exception:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

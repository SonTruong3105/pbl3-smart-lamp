import asyncio

from app.routes.esp32_ws import _audio_turn_worker, _enqueue_vad_audio


class _Handler:
    def __init__(self):
        self.errors = []

    async def _send_error(self, message):
        self.errors.append(message)


class _Log:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    def warning(self, message):
        self.messages.append(message)

    def exception(self, message):
        self.messages.append(message)


def test_voice_segments_are_processed_sequentially_in_order():
    async def run():
        queue = asyncio.Queue(maxsize=2)
        log = _Log()
        started = asyncio.Event()
        release_first = asyncio.Event()
        processed = []

        async def process(pcm, _source):
            processed.append(pcm)
            if pcm == b"first":
                started.set()
                await release_first.wait()

        worker = asyncio.create_task(_audio_turn_worker(queue, process, log))
        await asyncio.sleep(0)
        await _enqueue_vad_audio(queue, b"first", "vad", None, log)
        await started.wait()
        await _enqueue_vad_audio(queue, b"second", "vad", None, log)
        assert processed == [b"first"]
        release_first.set()
        await asyncio.wait_for(queue.join(), timeout=1)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        return processed

    assert asyncio.run(run()) == [b"first", b"second"]


def test_voice_queue_full_reports_overload_instead_of_silent_drop():
    async def run():
        queue = asyncio.Queue(maxsize=1)
        handler = _Handler()
        log = _Log()
        await _enqueue_vad_audio(queue, b"pending", "vad", handler, log)
        accepted = await _enqueue_vad_audio(queue, b"overflow", "vad", handler, log)
        return accepted, handler.errors, log.messages

    accepted, errors, messages = asyncio.run(run())
    assert accepted is False
    assert errors and "vui lòng nói lại" in errors[0]
    assert any("queue full" in message for message in messages)

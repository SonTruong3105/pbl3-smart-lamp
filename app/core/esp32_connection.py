"""ESP32ConnectionHandler — SINGLE audio sender."""
import asyncio
import io
import wave
from typing import Optional

from app.core.connection import ConnectionHandler
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio_rate_controller import AudioRateController
from app.core.utils.audio import run_ffmpeg, AudioConvertError

_COMPRESSED_OR_CONTAINER_HEADERS = (
    b"ID3",
    b"\xff\xfb",
    b"\xff\xf3",
    b"\xff\xf2",
    b"OggS",
    b"fLaC",
    b"\x1a\x45\xdf\xa3",
    b"RIFF",
    b"FORM",
    b"MThd",
)


class ESP32ConnectionHandler(ConnectionHandler):
    SAMPLE_RATE = 16000

    def __init__(self, ws, session_id, device_id):
        super().__init__(ws, session_id, device_id)
        self.opus = OpusCodec(sample_rate=self.SAMPLE_RATE, channels=1)
        self.rate_controller = AudioRateController(
            send_fn=self.ws.send_audio, frame_duration_ms=60, pre_buffer_count=3
        )
        self._tts_started = False
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._sender_task: Optional[asyncio.Task] = None
        self._sender_running = False
        self._sender_lock = asyncio.Lock()
        self._music_task: Optional[asyncio.Task] = None

    async def _ensure_sender(self):
        async with self._sender_lock:
            if self._sender_task is None or self._sender_task.done():
                self._sender_running = True
                self._sender_task = asyncio.create_task(self._audio_sender_loop())

    def _clear_queue_nowait(self):
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _audio_sender_loop(self):
        try:
            while self._sender_running:
                try:
                    item = await asyncio.wait_for(self._audio_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    break
                idx, _sentence, audio_bytes = item
                try:
                    frames = await self._audio_to_opus_frames(
                        audio_bytes, timeout=60.0 if idx == "music" else 15.0
                    )
                    if not frames:
                        self.log.warning(f"#{idx}: không có Opus frame")
                        continue
                    await self.rate_controller.reset_async()
                    for f in frames:
                        if not self._sender_running:
                            break
                        if f:
                            await self.rate_controller.send(f)
                    self.log.info(f"#{idx}: sent {len(frames)} frames")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.warning(f"#{idx}: sender lỗi: {e}")
        except asyncio.CancelledError:
            raise
        finally:
            self._sender_running = False
            self.log.info("🛑 Audio sender stopped")

    async def _stop_sender(self, drain=False, drain_timeout=30.0):
        async with self._sender_lock:
            task = self._sender_task
            if task is None:
                self._sender_running = False
                self._clear_queue_nowait()
                return

            if drain:
                # Không đặt _sender_running=False trước để sender xử lý hết phần còn lại
                try:
                    await asyncio.wait_for(self._audio_queue.put(None), timeout=5.0)
                except asyncio.TimeoutError:
                    self.log.warning("⏰ Drain timeout đặt sentinel — force cancel")
                    self._sender_running = False
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self._sender_task = None
                    self._clear_queue_nowait()
                    return

                try:
                    await asyncio.wait_for(task, timeout=drain_timeout)
                except asyncio.TimeoutError:
                    self.log.warning("⏰ Sender drain timeout — force cancel")
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                except (asyncio.CancelledError, Exception):
                    pass

                self._sender_running = False
            else:
                self._sender_running = False
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            self._sender_task = None
            self._clear_queue_nowait()

    async def _send_tts_stop_if_started(self):
        if not self._tts_started:
            return
        self._tts_started = False
        try:
            await asyncio.wait_for(
                self.ws.send_json({"type": "tts", "state": "stop"}), timeout=5.0
            )
        except Exception as e:
            self.log.warning(f"send tts stop lỗi: {e}")

    async def _stop_tts(self, cancel_audio=False, drain_timeout=30.0):
        if cancel_audio:
            await self._stop_sender(drain=False)
        else:
            await self._stop_sender(drain=True, drain_timeout=drain_timeout)
        await self.rate_controller.reset_async()
        await self._send_tts_stop_if_started()

    async def stop_music(self):
        """Cancel active/pending music without aborting the conversation pipeline."""
        self._pending_music = None
        task = self._music_task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._music_task = None
        await self._stop_sender(cancel_audio=True)
        await self.rate_controller.reset_async()
        await self._send_tts_stop_if_started()
        self._music_playing = False
        return task is not None

    async def _stop_audio(self):
        await self.stop_music()

    async def abort(self):
        music_task = self._music_task
        if music_task and not music_task.done():
            music_task.cancel()
            await asyncio.gather(music_task, return_exceptions=True)
        self._music_task = None
        self._music_playing = False

        # Hủy pipeline trước để ngăn phát sinh audio mới, sau đó dừng sender ngay
        try:
            await super().abort()
        except Exception:
            pass
        try:
            await self._stop_tts(cancel_audio=True)
        except Exception:
            pass

        # Per-turn interrupt: reset _closed để turn kế tiếp hoạt động bình thường
        self._closed = False

    async def _send_callback(self, payload):
        if self._closed or not isinstance(payload, dict):
            return

        try:
            await self._forward_to_linked_chats(payload)
        except Exception:
            pass

        try:
            await self._broadcast_observe(payload)
        except Exception:
            pass

        try:
            ptype = payload.get("type")
            if ptype == "audio":
                audio_bytes = payload.get("data")
                if not audio_bytes:
                    return
                self._captured["bot_mp3_parts"].append(audio_bytes)
                if not self._tts_started:
                    await self.ws.send_json({"type": "tts", "state": "start"})
                    self._tts_started = True
                sentence = payload.get("sentence") or ""
                if sentence:
                    await self.ws.send_json(
                        {"type": "tts", "state": "sentence_start", "text": sentence}
                    )
                idx = payload.get("index", 1)
                await self._ensure_sender()
                try:
                    self._audio_queue.put_nowait((idx, sentence, audio_bytes))
                except asyncio.QueueFull:
                    self.log.warning(f"⚠️ Audio queue đầy — bỏ #{idx}")
            elif ptype == "stt":
                await self.ws.send_json({"type": "stt", "text": payload.get("text", "")})
            elif ptype in ("tts_start", "status", "token", "tool", "user_wav"):
                pass
            elif ptype in ("tts_stop", "end"):
                await self._stop_tts(cancel_audio=False)
            elif ptype == "listen":
                self.log.info("🎤 Gửi lệnh mở Mic xuống ESP32...")
                listen_msg = {"type": "listen"}
                if "state" in payload:
                    listen_msg["state"] = payload["state"]
                if "mode" in payload:
                    listen_msg["mode"] = payload["mode"]
                await self.ws.send_json(listen_msg)
            elif ptype == "goodbye":
                self.log.info("👋 Gửi lệnh kết thúc phiên thoại xuống ESP32...")
                await self.ws.send_json({"type": "goodbye"})
            elif ptype == "error":
                err_text = payload.get("text", "")
                self.log.warning(f"Error -> thiết bị: {err_text}")
                await self._stop_tts(cancel_audio=True)
                if err_text:
                    await self.ws.send_json({"type": "error", "text": err_text})
            else:
                self.log.debug(f"Skip type={ptype}")
        except Exception as e:
            self.log.warning(f"send_callback: {e}")
    async def _broadcast_observe(self, payload):
        try:
            from app.core.device_hub import get_device_hub

            ptype = payload.get("type")
            if ptype in ("music", "audio", "user_wav"):
                return
            if ptype in ("token", "stt", "end", "tts", "tool", "status", "error", "listen"):
                await get_device_hub().broadcast_event(self.device_id, payload)
        except Exception:
            pass

    async def _forward_to_linked_chats(self, payload):
        """Forward text events đến web chat đã link. Skip audio."""
        try:
            ptype = payload.get("type")
            if ptype not in ("token", "stt", "end", "error", "tool", "lamp_state"):
                return
            from app.core.device_hub import get_device_hub

            linked = get_device_hub().get_chats_by_device(self.device_id)
            if not linked:
                return
            for _web_id, chat_ws in linked:
                try:
                    await chat_ws.send_json(payload)
                except Exception:
                    pass
        except Exception:
            pass

    async def flush_pending_music(self):
        pending_music = self._pending_music
        self._pending_music = None
        if not pending_music or not pending_music.get("audio"):
            return
        if self._music_task and not self._music_task.done():
            await self.stop_music()
        self._music_playing = True
        self._music_task = asyncio.create_task(self._play_music(pending_music))

    async def _play_music(self, pending_music):
        self.log.info(f"🎵 Gửi music xuống ESP32: {pending_music.get('label', '')!r}")
        try:
            await self._stop_tts(cancel_audio=False, drain_timeout=120.0)
            self._tts_started = True
            await self.ws.send_json({"type": "tts", "state": "start"})
            await self.ws.send_json(
                {
                    "type": "tts",
                    "state": "sentence_start",
                    "text": pending_music.get("label", ""),
                }
            )
            await self._ensure_sender()
            await self._audio_queue.put(
                ("music", pending_music.get("label", ""), pending_music["audio"])
            )
            await self._audio_queue.put(None)
            task = self._sender_task
            if task is not None:
                await task
            async with self._sender_lock:
                if self._sender_task is task:
                    self._sender_task = None
                self._sender_running = False
            await self.rate_controller.reset_async()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.warning(f"Music playback lỗi: {e}")
        finally:
            self._music_playing = False
            await self._send_tts_stop_if_started()

    @staticmethod
    def _is_plausible_raw_pcm(audio_bytes: bytes) -> bool:
        if not audio_bytes or len(audio_bytes) < 320 or (len(audio_bytes) % 2) != 0:
            return False
        if any(audio_bytes.startswith(sig) for sig in _COMPRESSED_OR_CONTAINER_HEADERS):
            return False
        # Tránh nhầm file WAV (bắt đầu RIFF và có chunk WAVE) với raw PCM
        if b"WAVE" in audio_bytes[:16]:
            return False
        return True

    async def _audio_to_opus_frames(self, audio_bytes, timeout=15.0):
        try:
            pcm = None
            if audio_bytes:
                if audio_bytes.startswith(b"RIFF"):
                    try:
                        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                            if (
                                wf.getframerate() == self.SAMPLE_RATE
                                and wf.getnchannels() == 1
                                and wf.getsampwidth() == 2
                                and wf.getcomptype() == "NONE"
                            ):
                                pcm = wf.readframes(wf.getnframes())
                    except Exception:
                        pcm = None
                elif self._is_plausible_raw_pcm(audio_bytes):
                    pcm = audio_bytes

            if pcm is None:
                pcm = await run_ffmpeg(
                    [
                        "-i",
                        "pipe:0",
                        "-f",
                        "s16le",
                        "-acodec",
                        "pcm_s16le",
                        "-ac",
                        "1",
                        "-ar",
                        str(self.SAMPLE_RATE),
                        "pipe:1",
                    ],
                    audio_bytes,
                    timeout=timeout,
                )

            if pcm:
                return self.opus.encode_frames(pcm)
            return []
        except AudioConvertError as e:
            self.log.error(f"Audio->Opus: {e}")
            return []
        except Exception as e:
            self.log.error(f"Audio->Opus lỗi: {type(e).__name__}: {e}")
            return []
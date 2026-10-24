import asyncio
"""ESP32ConnectionHandler - convert audio sang Opus."""
from app.core.connection import ConnectionHandler
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio_rate_controller import AudioRateController
from app.core.utils.audio import run_ffmpeg, AudioConvertError


class ESP32ConnectionHandler(ConnectionHandler):
    SAMPLE_RATE = 24000

    def __init__(self, ws, session_id: int, device_id: str):
        super().__init__(ws, session_id, device_id)
        self.opus = OpusCodec(sample_rate=self.SAMPLE_RATE, channels=1)
        self.rate_controller = AudioRateController(
            send_fn=self.ws.send_audio,
            frame_duration_ms=60,
            pre_buffer_count=3,
        )
        self._tts_started = False

    async def _stop_tts(self):
        """Bao thiet bi dung phat (idempotent)."""
        started = self._tts_started
        self._tts_started = False
        self.rate_controller.reset()
        if started:
            await self.ws.send_json({"type": "tts", "state": "stop"})

    async def _send_callback(self, payload: dict):
        try:
            ptype = payload["type"]

            if ptype == "audio":
                audio_bytes = payload["data"]
                self._captured["bot_mp3_parts"].append(audio_bytes)

                if not self._tts_started:
                    await self.ws.send_json({"type": "tts", "state": "start"})
                    self._tts_started = True

                sentence = payload.get("sentence") or ""
                if sentence:
                    await self.ws.send_json({
                        "type": "tts",
                        "state": "sentence_start",
                        "text": sentence,
                    })

                # ── Convert + pace audio trong task riêng (KHÔNG block handler) ──
                # rate_controller.send() cần pacing 60ms/frame — với audio dài
                # (729KB ≈ 370 frames) sẽ block ~22s nếu await trong loop.
                # Chạy task riêng → handler nhận message mới ngay lập tức.
                idx = payload.get("index", 1)
                if not hasattr(self, "_audio_tasks"):
                    self._audio_tasks: dict[int, asyncio.Task] = {}

                async def _send_audio_task(_audio_bytes=audio_bytes, _idx=idx):
                    try:
                        opus_frames = await self._audio_to_opus_frames(_audio_bytes)
                        if not opus_frames:
                            self.log.warning(f"#{_idx}: không có Opus frame")
                            return
                        self.log.info(
                            f"#{_idx}: {len(opus_frames)} Opus frames "
                            f"({len(opus_frames) * 60 / 1000:.1f}s pacing)"
                        )
                        self.rate_controller.reset()
                        for frame in opus_frames:
                            if frame:
                                await self.rate_controller.send(frame)
                        self.log.info(f"#{_idx}: sent {len(opus_frames)} frames")
                    except asyncio.CancelledError:
                        self.log.info(f"#{_idx}: audio task cancelled")
                        raise
                    except Exception as e:
                        self.log.warning(f"#{_idx}: audio task lỗi: {e}")
                    finally:
                        self._audio_tasks.pop(_idx, None)

                # Cancel task cũ cùng index nếu có
                old_task = self._audio_tasks.get(idx)
                if old_task and not old_task.done():
                    old_task.cancel()

                self._audio_tasks[idx] = asyncio.create_task(
                    _send_audio_task()
                )

            elif ptype == "stt":
                await self.ws.send_json({
                    "type": "stt",
                    "text": payload.get("text", ""),
                })

            elif ptype == "tts_start":
                pass

            elif ptype == "tts_stop":
                await self._stop_tts()

            elif ptype == "end":
                await self._stop_tts()

            elif ptype in ("status", "token", "tool", "user_wav"):
                pass

            elif ptype == "error":
                self.log.warning(f"Error -> thiet bi: {payload.get('text')}")

            else:
                self.log.debug(f"Skip type={ptype}")

        except Exception as e:
            self.log.warning(f"send_callback: {e}")

    async def _audio_to_opus_frames(self, audio_bytes: bytes) -> list:
        """Audio (MP3/WAV) -> PCM 24kHz mono -> LIST Opus frames."""
        try:
            pcm = await run_ffmpeg(
                [
                    "-i", "pipe:0",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ac", "1", "-ar", str(self.SAMPLE_RATE),
                    "pipe:1",
                ],
                audio_bytes,
                timeout=15.0,
            )
            return self.opus.encode_frames(pcm)
        except AudioConvertError as e:
            self.log.error(f"Audio->Opus: {e}")
            return []
        except Exception as e:
            self.log.error(f"Audio->Opus frames loi: {type(e).__name__}: {e}")
            return []

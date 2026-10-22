"""ESP32ConnectionHandler — convert audio sang Opus."""
import asyncio
import subprocess

from app.core.connection import ConnectionHandler
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio_rate_controller import AudioRateController


class ESP32ConnectionHandler(ConnectionHandler):
    SAMPLE_RATE = 24000

    def __init__(self, ws, session_id: int, device_id: str):
        super().__init__(ws, session_id, device_id)
        self.opus = OpusCodec(sample_rate=self.SAMPLE_RATE, channels=1)
        self.rate_controller = AudioRateController(
            send_fn=self.ws.send_audio,
            frame_duration_ms=60,
            pre_buffer_count=3,   # 3 frame đầu gửi ngay
        )
        self._tts_started = False

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

                opus_frames = await self._audio_to_opus_frames(audio_bytes)
                self.log.info(f"🔊 {len(opus_frames)} Opus frames (rate-controlled)")

                # ✅ Reset rate controller cho câu mới
                self.rate_controller.reset()
                for frame in opus_frames:
                    if frame:
                        await self.rate_controller.send(frame)
                self.log.info(f"✅ Sent {len(opus_frames)} frames")

            elif ptype == "stt":
                await self.ws.send_json({
                    "type": "stt",
                    "text": payload.get("text", ""),
                })

            elif ptype == "tts_start":
                pass

            elif ptype == "tts_stop":
                if self._tts_started:
                    await self.ws.send_json({"type": "tts", "state": "stop"})
                    self._tts_started = False
                self.rate_controller.reset()

            elif ptype in ("status", "token", "tool", "user_wav", "end"):
                pass

            else:
                self.log.debug(f"⏭️ Skip type={ptype}")

        except Exception as e:
            self.log.warning(f"⚠️ send_callback: {e}")

    async def _audio_to_opus_frames(self, audio_bytes: bytes) -> list:
        """Audio (MP3/WAV) → PCM 24kHz mono → LIST Opus frames."""
        def _convert():
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-i", "pipe:0",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ac", "1", "-ar", str(self.SAMPLE_RATE),
                    "pipe:1",
                ],
                input=audio_bytes,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="ignore"))
            return proc.stdout

        try:
            pcm = await asyncio.to_thread(_convert)
            return self.opus.encode_frames(pcm)
        except Exception as e:
            self.log.error(f"❌ Audio→Opus frames lỗi: {e}")
            return []

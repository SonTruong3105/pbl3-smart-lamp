"""Audio convert helpers."""
import asyncio
import subprocess
from loguru import logger


class AudioConvertError(Exception):
    pass


async def any_to_wav(audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
    def _run():
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-i", "pipe:0",
                    "-f", "wav",
                    "-acodec", "pcm_s16le",
                    "-ac", "1",
                    "-ar", str(sample_rate),
                    "pipe:1",
                ],
                input=audio_bytes,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise AudioConvertError("ffmpeg timeout sau 30s")

        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore")
            logger.error(f"ffmpeg lỗi: {err}")
            raise AudioConvertError(f"ffmpeg failed: {err[:200]}")

        return proc.stdout

    return await asyncio.to_thread(_run)
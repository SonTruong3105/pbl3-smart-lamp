"""Audio convert helpers - ffmpeg chay trong thread, kill duoc khi timeout/cancel.

Khong dung asyncio.create_subprocess_exec vi no nem NotImplementedError tren
SelectorEventLoop (Windows). Popen + to_thread chay duoc tren moi loai loop.
"""
import asyncio
import subprocess
import sys

from loguru import logger


class AudioConvertError(Exception):
    pass


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _run_ffmpeg_blocking(args: list, data: bytes, timeout: float, holder: dict) -> bytes:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        raise AudioConvertError("Khong tim thay ffmpeg trong PATH")

    holder["proc"] = proc
    try:
        out, err = proc.communicate(input=data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=2.0)
        except Exception:
            pass
        raise AudioConvertError(f"ffmpeg timeout {timeout}s - da kill")

    if proc.returncode != 0:
        msg = err.decode(errors="ignore")[:200]
        raise AudioConvertError(f"ffmpeg failed: {msg}")
    return out


async def run_ffmpeg(args: list, data: bytes, timeout: float = 15.0) -> bytes:
    """Chay ffmpeg (stdin=data) va tra stdout. Kill process khi bi cancel."""
    holder: dict = {}
    try:
        return await asyncio.to_thread(_run_ffmpeg_blocking, args, data, timeout, holder)
    except asyncio.CancelledError:
        proc = holder.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        raise


async def any_to_wav(audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Convert audio bat ky -> WAV PCM16 mono."""
    try:
        return await run_ffmpeg(
            [
                "-i", "pipe:0",
                "-f", "wav",
                "-acodec", "pcm_s16le",
                "-ac", "1",
                "-ar", str(sample_rate),
                "pipe:1",
            ],
            audio_bytes,
            timeout=15.0,
        )
    except AudioConvertError as e:
        logger.error(f"ffmpeg loi: {e}")
        raise

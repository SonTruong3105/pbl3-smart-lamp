"""VieNeu-TTS provider — Semaphore(3) + ONNX streaming ready."""
import asyncio
import time
import httpx
from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts
from app.config import config as _app_config
from app.core.utils.tts_cache import get_cache


import io as _io
import wave as _wave


def _prepend_silence_wav(
    wav_bytes: bytes, silence_ms: int, max_duration_ms: int = 3000
) -> bytes:
    """Prepend silence_ms of silence to WAV header.

    Only applied for short audio (< max_duration_ms) — fixes VieNeu TTS
    clipping the first syllable on very short phrases (e.g. "Chào bạn!").
    Long audio is returned unchanged to avoid adding latency.
    """
    if silence_ms <= 0 or not wav_bytes:
        return wav_bytes
    try:
        src_buf = _io.BytesIO(wav_bytes)
        with _wave.open(src_buf, "rb") as src_wav:
            params = src_wav.getparams()
            duration_ms = params.nframes / params.framerate * 1000
            if duration_ms > max_duration_ms:
                return wav_bytes
            frames = src_wav.readframes(src_wav.getnframes())

        silence_samples = int(params.framerate * silence_ms / 1000)
        silence_bytes = b"\x00" * (
            silence_samples * params.nchannels * params.sampwidth
        )

        out_buf = _io.BytesIO()
        with _wave.open(out_buf, "wb") as dst_wav:
            dst_wav.setparams(params)
            dst_wav.writeframes(silence_bytes + frames)
        return out_buf.getvalue()
    except Exception:
        return wav_bytes


# VieNeu inference is serialized by the backend; parallel requests increase latency.
# [FIX] điều chỉnh bằng env VIENEU_CONCURRENCY (mặc định 1 = an toàn)
import os as _os
_VIENEU_CONCURRENCY = max(1, int(_os.getenv("VIENEU_CONCURRENCY", "1")))
_vieneu_sem = asyncio.Semaphore(_VIENEU_CONCURRENCY)
_vieneu_client: httpx.AsyncClient | None = None


async def _get_vieneu_client() -> httpx.AsyncClient:
    global _vieneu_client
    if _vieneu_client is None or _vieneu_client.is_closed:
        _vieneu_client = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=3, max_connections=3),
            headers={"Connection": "keep-alive"},
        )
    return _vieneu_client


async def close_vieneu_client() -> None:
    global _vieneu_client
    if _vieneu_client is not None and not _vieneu_client.is_closed:
        await _vieneu_client.aclose()
    _vieneu_client = None


class VieNeuTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not text.strip(): return b""
        clean = clean_for_tts(text)
        if not clean: return b""

        url = self.config.get("url", "http://localhost:11436")
        voice = kwargs.get("voice") or self.config.get("voice", "Trúc Ly")
        cache = get_cache()
        cached = cache.get(clean, voice)
        if cached:
            self.log.debug(f"⚡ VieNeu cache hit voice={voice!r}: {len(cached)}b")
            return cached
        timeout = min(float(self.config.get("request_timeout", 15.0)), 30.0)

        try:
            await asyncio.wait_for(_vieneu_sem.acquire(), timeout=20.0)
        except asyncio.TimeoutError:
            self.log.error("🚨 Không giành được TTS semaphore sau 20s")
            return b""

        t0 = time.perf_counter()
        try:
            client = await _get_vieneu_client()
            cfg = httpx.Timeout(connect=3.0, read=timeout, write=3.0, pool=3.0)
            r = await client.post(
                f"{url}/tts",
                json={"text": clean, "voice": voice},
                timeout=cfg,
            )
            r.raise_for_status()
            wav = r.content
            _silence_ms = int(_app_config._get("TTS", "prepend_silence_ms", default=150))
            wav = _prepend_silence_wav(wav, _silence_ms)
            cache.put(clean, wav, voice)

            elapsed = (time.perf_counter() - t0) * 1000
            self.log.info(f"🔊 VieNeu [{elapsed:.0f}ms] voice={voice!r}: {len(wav)}b")
            return wav
        except Exception as e:
            self.log.error(f"❌ VieNeu lỗi: {type(e).__name__}: {e}")
            return b""
        finally:
            _vieneu_sem.release()


ProviderRegistry.register_tts("vieneu", VieNeuTTSProvider)
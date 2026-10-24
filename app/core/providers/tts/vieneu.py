"""VieNeu-TTS provider (Đã bỏ Global Lock)"""
import asyncio
import json
import subprocess
import sys
import time
from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts
from app.core.utils.tts_cache import get_cache

_CURL = "curl.exe" if sys.platform == "win32" else "curl"

class VieNeuTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not text.strip(): return b""
        clean = clean_for_tts(text)
        if not clean: return b""

        url = self.config.get("url", "http://localhost:11436")
        voice = kwargs.get("voice") or self.config.get("voice", "Trúc Ly")
        timeout = min(float(self.config.get("request_timeout", 15.0)), 12.0)

        _cache = get_cache()
        _hit = _cache.get(clean, voice)
        if _hit: return _hit

        t_start = time.perf_counter()
        try:
            wav_bytes = await self._do_request_async(clean, voice, url, timeout)
            elapsed = (time.perf_counter() - t_start) * 1000
            if not wav_bytes:
                self.log.warning(f"⚠️ VieNeu rỗng sau {elapsed:.0f}ms")
                return b""
            _cache.put(clean, wav_bytes, voice)
            self.log.info(f"🔊 VieNeu [{elapsed:.0f}ms] | {len(wav_bytes)}b")
            return wav_bytes
        except Exception as e:
            self.log.error(f"❌ VieNeu lỗi: {e}")
            return b""

    async def _do_request_async(self, clean: str, voice: str, url: str, timeout: float) -> bytes:
        def _run() -> bytes:
            payload = json.dumps({"text": clean, "voice": voice}, ensure_ascii=False).encode("utf-8")
            proc = subprocess.Popen(
                [_CURL, "-sS", "-X", "POST", f"{url}/tts", "-H", "Content-Type: application/json; charset=utf-8", "-H", "Connection: close", "--no-keepalive", "--max-time", str(timeout), "--data-binary", "@-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                stdout, stderr = proc.communicate(input=payload, timeout=timeout + 3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                return b""
            if proc.returncode != 0: return b""
            return stdout
        try:
            return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout + 5.0)
        except Exception:
            return b""

ProviderRegistry.register_tts("vieneu", VieNeuTTSProvider)

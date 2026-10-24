"""VieNeu-TTS provider — dùng curl subprocess + lock timeout.

Bug fix chi tiết:
- Lock có timeout acquire (5s) — nếu request cũ treo, câu mới bỏ qua thay vì chờ vĩnh viễn
- subprocess.Popen + kill() — kill được process con khi treo
- Không dùng requests/httpx (tránh bug SelectorEventLoop)
- Cleanup lock tự động qua try/finally
"""
import asyncio
import json
import subprocess
import sys
import time

from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts
from app.core.utils.tts_cache import get_cache


_vieneu_lock = asyncio.Lock()
_consecutive_timeouts = 0
_LOCK_ACQUIRE_TIMEOUT = 5.0
_LAST_LOCK_RELEASE = time.time()

_CURL = "curl.exe" if sys.platform == "win32" else "curl"


class VieNeuTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        global _consecutive_timeouts, _LAST_LOCK_RELEASE

        if not text.strip():
            return b""

        clean = clean_for_tts(text)
        if not clean:
            self.log.debug(f"⚠️ Text rỗng sau normalize: '{text[:60]}'")
            return b""

        url = self.config.get("url", "http://localhost:11436")
        voice = kwargs.get("voice") or self.config.get("voice", "Trúc Ly")
        timeout = min(float(self.config.get("request_timeout", 15.0)), 12.0)

        # TTS cache: trả ngay nếu câu đã có (giảm ~800ms -> ~50ms)
        _cache = get_cache()
        _hit = _cache.get(clean, voice)
        if _hit:
            self.log.debug(f"TTS cache hit: {clean[:40]!r}")
            return _hit

        # Lock có timeout — không chờ vô hạn
        try:
            await asyncio.wait_for(
                _vieneu_lock.acquire(),
                timeout=_LOCK_ACQUIRE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self.log.error(
                f"🚨 VieNeu lock treo >{_LOCK_ACQUIRE_TIMEOUT}s — "
                f"lần release cuối {time.time() - _LAST_LOCK_RELEASE:.1f}s trước. "
                f"Bỏ qua câu này."
            )
            _consecutive_timeouts += 1
            return b""

        t_start = time.perf_counter()
        self.log.debug(f"🔒 VieNeu lock: {clean[:40]!r}")

        try:
            wav_bytes = await self._do_request_async(clean, voice, url, timeout)
            elapsed = (time.perf_counter() - t_start) * 1000

            if not wav_bytes:
                _consecutive_timeouts += 1
                self.log.warning(
                    f"⚠️ VieNeu rỗng sau {elapsed:.0f}ms "
                    f"(#{_consecutive_timeouts})"
                )
                if _consecutive_timeouts >= 3:
                    self.log.error(
                        "🚨 VieNeu treo 3 lần liên tiếp — "
                        "kiểm tra lại VieNeu server!"
                    )
                return b""

            _consecutive_timeouts = 0
            _cache.put(clean, wav_bytes, voice)
            self.log.info(
                f"🔊 VieNeu [{elapsed:.0f}ms] voice={voice!r}: "
                f"{len(wav_bytes)}b | {clean[:40]!r}"
            )
            return wav_bytes

        finally:
            elapsed = (time.perf_counter() - t_start) * 1000
            self.log.debug(f"🔓 VieNeu release sau {elapsed:.0f}ms")
            _LAST_LOCK_RELEASE = time.time()
            _vieneu_lock.release()

    async def _do_request_async(
        self, clean: str, voice: str, url: str, timeout: float
    ) -> bytes:
        """Chạy curl trong thread, có timeout OS-level."""

        def _run() -> bytes:
            payload = json.dumps(
                {"text": clean, "voice": voice},
                ensure_ascii=False,
            ).encode("utf-8")

            proc = subprocess.Popen(
                [
                    _CURL,
                    "-sS",
                    "-X", "POST",
                    f"{url}/tts",
                    "-H", "Content-Type: application/json; charset=utf-8",
                    "-H", "Connection: close",
                    "--no-keepalive",
                    "--max-time", str(timeout),
                    "--data-binary", "@-",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout, stderr = proc.communicate(
                    input=payload,
                    timeout=timeout + 3.0,
                )
            except subprocess.TimeoutExpired:
                self.log.error(f"⏰ curl KILL sau {timeout + 3.0}s")
                proc.kill()
                try:
                    proc.communicate(timeout=2.0)
                except Exception:
                    pass
                return b""

            if proc.returncode != 0:
                err = stderr.decode(errors="ignore")[:200]
                self.log.error(f"❌ curl rc={proc.returncode}: {err}")
                return b""

            return stdout

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=timeout + 5.0,
            )
        except asyncio.TimeoutError:
            self.log.error(f"⏰ to_thread timeout sau {timeout + 5.0}s")
            return b""
        except Exception as e:
            self.log.error(f"❌ VieNeu lỗi: {type(e).__name__}: {e}")
            return b""


ProviderRegistry.register_tts("vieneu", VieNeuTTSProvider)

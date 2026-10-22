"""Piper TTS provider."""
import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path
from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts


class PiperTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not text.strip():
            return b""
        clean = clean_for_tts(text)
        if not clean:
            return b""

        model_path = self.config.get("piper_model")
        if not Path(model_path).exists():
            self.log.error(f"❌ Không tìm thấy Piper model: {model_path}")
            return b""

        binary = self.config.get("piper_binary", "python")
        timeout = self.config.get("request_timeout", 30.0)

        def _run():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                out_path = tmp.name
            try:
                proc = subprocess.run(
                    [binary, "-m", "piper",
                     "--model", model_path,
                     "--output_file", out_path],
                    input=clean.encode("utf-8"),
                    capture_output=True,
                    timeout=timeout,
                )
                if proc.returncode != 0:
                    err = proc.stderr.decode(errors="ignore")
                    raise RuntimeError(f"Piper fail: {err[:200]}")
                with open(out_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)

        try:
            start = time.perf_counter()
            wav = await asyncio.to_thread(_run)
            elapsed = (time.perf_counter() - start) * 1000
            if wav:
                self.log.info(f"🔊 Piper [{elapsed:.0f}ms]: {len(wav)}b")
                return wav
        except Exception as e:
            self.log.error(f"❌ Piper lỗi: {e}")
        return b""


ProviderRegistry.register_tts("piper", PiperTTSProvider)
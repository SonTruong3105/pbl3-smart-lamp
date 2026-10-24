"""PhoWhisper ASR provider."""
import httpx
from app.core.providers.base import ASRProviderBase, ProviderRegistry


_asr_client: httpx.AsyncClient | None = None


def _get_client(timeout: float) -> httpx.AsyncClient:
    global _asr_client
    if _asr_client is None or _asr_client.is_closed:
        _asr_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _asr_client


class PhoWhisperProvider(ASRProviderBase):
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        language = language or self.config.get("language", "vi")
        url = self.config.get("url")
        model = self.config.get("model", "phowhisper")
        timeout = self.config.get("request_timeout", 60.0)

        try:
            client = _get_client(timeout)
            files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
            data = {"language": language, "model": model}
            r = await client.post(url, files=files, data=data)
            r.raise_for_status()
            text = r.json().get("text", "").strip()
            self.log.info(f"📝 ASR: {text}")
            return text
        except httpx.ConnectError:
            self.log.error("❌ Không kết nối được ASR server")
            return ""
        except httpx.TimeoutException:
            self.log.error("❌ ASR timeout")
            return ""
        except Exception as e:
            self.log.error(f"❌ ASR lỗi: {e}")
            return ""


ProviderRegistry.register_asr("phowhisper", PhoWhisperProvider)
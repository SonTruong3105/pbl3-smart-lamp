"""PhoWhisper ASR provider."""
import httpx
from app.core.providers.base import ASRProviderBase, ProviderRegistry


_asr_client: httpx.AsyncClient | None = None


def _get_client(timeout: float = 60.0) -> httpx.AsyncClient:
    """Return a pooled client; apply request-specific timeout in ``transcribe``."""
    global _asr_client
    if _asr_client is None or _asr_client.is_closed:
        _asr_client = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _asr_client


async def close_asr_client() -> None:
    global _asr_client
    client, _asr_client = _asr_client, None
    if client is not None and not client.is_closed:
        await client.aclose()


class PhoWhisperProvider(ASRProviderBase):
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        language = language or self.config.get("language", "vi")
        url = self.config.get("url")
        model = self.config.get("model", "phowhisper")
        timeout = self.config.get("request_timeout", 60.0)

        try:
            client = _get_client()
            files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
            data = {"language": language, "model": model}
            r = await client.post(
                url,
                files=files,
                data=data,
                timeout=httpx.Timeout(float(timeout)),
            )
            r.raise_for_status()
            try:
                body = r.json()
            except ValueError:
                self.log.error("❌ ASR trả JSON không hợp lệ")
                return ""
            if not isinstance(body, dict) or not isinstance(body.get("text", ""), str):
                self.log.error("❌ ASR trả response không đúng định dạng")
                return ""
            text = body.get("text", "").strip()
            if text:
                self.log.info(f"📝 ASR: {text}")
            else:
                self.log.info("📝 ASR trả transcript rỗng (không nhận diện được lời nói)")
            return text
        except httpx.ConnectError:
            self.log.error("❌ Không kết nối được ASR server")
            return ""
        except httpx.TimeoutException:
            self.log.error(f"❌ ASR timeout sau {timeout}s")
            return ""
        except httpx.HTTPStatusError as e:
            self.log.error(f"❌ ASR HTTP {e.response.status_code}")
            return ""
        except Exception as e:
            self.log.error(f"❌ ASR lỗi: {type(e).__name__}: {e}")
            return ""


ProviderRegistry.register_asr("phowhisper", PhoWhisperProvider)

class ChunkFormerProvider(PhoWhisperProvider):
    """Reuse the local multipart transcription protocol for ChunkFormer."""
    pass


ProviderRegistry.register_asr("chunkformer", ChunkFormerProvider)

"""PhoWhisper ASR provider."""
import httpx
from app.core.providers.base import ASRProviderBase, ProviderRegistry


class PhoWhisperProvider(ASRProviderBase):
    async def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        language = language or self.config.get("language", "vi")
        url = self.config.get("url")
        model = self.config.get("model", "phowhisper")
        timeout = self.config.get("request_timeout", 60.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
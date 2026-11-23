"""ChunkFormer provider using its OpenAI-compatible local ASR endpoint."""
from app.core.providers.asr.phowhisper import PhoWhisperProvider
from app.core.providers.base import ProviderRegistry


class ChunkFormerProvider(PhoWhisperProvider):
    """Reuse the local multipart transcription protocol for ChunkFormer."""


ProviderRegistry.register_asr("chunkformer", ChunkFormerProvider)

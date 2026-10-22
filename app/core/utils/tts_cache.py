"""TTS cache — cache audio cho câu phổ biến."""
import hashlib
from collections import OrderedDict


class TTSCache:
    def __init__(self, max_size: int = 100):
        self._cache = OrderedDict()
        self.max_size = max_size

    def _key(self, text: str, voice: str = "") -> str:
        return hashlib.md5(f"{voice}:{text}".encode()).hexdigest()

    def get(self, text: str, voice: str = "") -> bytes:
        key = self._key(text, voice)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, text: str, audio: bytes, voice: str = ""):
        if not audio or len(audio) > 500_000:
            return
        key = self._key(text, voice)
        self._cache[key] = audio
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)


_cache = TTSCache(max_size=200)


def get_cache() -> TTSCache:
    return _cache

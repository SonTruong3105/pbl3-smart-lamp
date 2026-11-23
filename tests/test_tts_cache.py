"""Unit tests cho TTSCache (LRU behavior)."""
from app.core.utils.tts_cache import TTSCache


class TestTTSCache:
    def test_put_and_get(self):
        c = TTSCache(max_size=3)
        c.put("hello", b"audio1", "voice1")
        assert c.get("hello", "voice1") == b"audio1"

    def test_voice_isolation(self):
        c = TTSCache(max_size=10)
        c.put("hello", b"a1", "v1")
        c.put("hello", b"a2", "v2")
        assert c.get("hello", "v1") == b"a1"
        assert c.get("hello", "v2") == b"a2"

    def test_lru_eviction(self):
        c = TTSCache(max_size=2)
        c.put("a", b"1")
        c.put("b", b"2")
        c.get("a")            # Touch a
        c.put("c", b"3")      # Evict b
        assert c.get("a") == b"1"
        assert c.get("b") is None
        assert c.get("c") == b"3"

    def test_oversize_rejected(self):
        c = TTSCache(max_size=10)
        c.put("big", b"x" * 600_000)   # > 500KB limit
        assert c.get("big") is None

    def test_empty_audio_rejected(self):
        c = TTSCache(max_size=10)
        c.put("empty", b"")
        assert c.get("empty") is None
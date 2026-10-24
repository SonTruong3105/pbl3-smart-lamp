"""Wake word - device mode (ESP32) hoac server mode (Porcupine)."""
import re
from loguru import logger

try:
    import pvporcupine
    from pvrecorder import PvRecorder
    HAS_PORCUPINE = True
except ImportError:
    HAS_PORCUPINE = False


DEFAULT_WAKE_WORDS = ["đèn ơi", "hey đèn", "chào đèn", "đèn"]


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"[.!?,;:…]+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def matches_wake_word(text: str, allowed_words: list = None) -> bool:
    words = allowed_words or DEFAULT_WAKE_WORDS
    t = normalize(text)
    if not t:
        return True
    for w in words:
        if normalize(w) in t or t in normalize(w):
            return True
    return False


class PorcupineWakeWord:
    def __init__(self, access_key: str, keyword_paths: list = None, keywords: list = None):
        if not HAS_PORCUPINE:
            raise ImportError("Can: pip install pvporcupine pvrecorder")
        if keyword_paths:
            self.porcupine = pvporcupine.create(
                access_key=access_key, keyword_paths=keyword_paths,
            )
        else:
            self.porcupine = pvporcupine.create(
                access_key=access_key, keywords=keywords or ["hey google"],
            )
        self.recorder = PvRecorder(
            frame_length=self.porcupine.frame_length, device_index=-1,
        )

    def listen_once(self, timeout: float = 10.0) -> bool:
        import struct, time
        self.recorder.start()
        start = time.time()
        try:
            while time.time() - start < timeout:
                pcm = self.recorder.read()
                pcm_unpacked = struct.unpack_from(
                    "h" * self.porcupine.frame_length, pcm,
                )
                if self.porcupine.process(pcm_unpacked) >= 0:
                    logger.info("Wake word detected (server mode)")
                    return True
            return False
        finally:
            self.recorder.stop()

    def close(self):
        try:
            self.porcupine.delete()
            self.recorder.delete()
        except Exception:
            pass

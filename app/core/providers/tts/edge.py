"""Edge TTS provider với normalization."""
import asyncio
import time
import re
import edge_tts
from app.core.providers.base import TTSProviderBase, ProviderRegistry


# === Emoji ===
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
    "\U00002700-\U000027BF\U0001F1E0-\U0001F1FF"
    "\U0000FE00-\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)

# === Markdown ===
LIST_MARKER_PATTERN = re.compile(r"(?m)^\s*(?:[*\-+•]|\d+[.)])\s+")
BOLD_ITALIC_PATTERN = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}|_{1,3}([^_\n]+?)_{1,3}")
HEADING_PATTERN = re.compile(r"(?m)^#{1,6}\s+")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+?)`")

# === Normalize ===
DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
TIME_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\b")
PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
DEGREE_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*[CcFf]")
DECIMAL_PATTERN = re.compile(r"\b(\d+)\.(\d{1,2})(?!\d)")
SPECIAL_CHARS_PATTERN = re.compile(r"[*_`~#>\[\]{}()|\\/]+")
MULTI_SPACE_PATTERN = re.compile(r"\s+")


def _replace_date(m):
    d, mo, y = m.group(1), m.group(2), m.group(3)
    return f"{d} tháng {mo} năm {y}" if y else f"{d} tháng {mo}"


def _replace_time(m):
    h, mi = m.group(1), m.group(2)
    return f"{h} giờ" if mi == "00" else f"{h} giờ {mi}"


def _replace_percent(m):
    return f"{m.group(1)} phần trăm"


def _replace_degree(m):
    return f"{m.group(1)} độ C"


def _replace_decimal(m):
    return f"{m.group(1)} phẩy {m.group(2)}"


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\n+", ". ", text)
    text = LIST_MARKER_PATTERN.sub("", text)
    text = BOLD_ITALIC_PATTERN.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = HEADING_PATTERN.sub("", text)
    text = INLINE_CODE_PATTERN.sub(r"\1", text)
    return text


def clean_for_tts(text: str) -> str:
    if not text:
        return ""
    text = _strip_markdown(text)
    text = DATE_PATTERN.sub(_replace_date, text)
    text = TIME_PATTERN.sub(_replace_time, text)
    text = DEGREE_PATTERN.sub(_replace_degree, text)
    text = PERCENT_PATTERN.sub(_replace_percent, text)
    text = DECIMAL_PATTERN.sub(_replace_decimal, text)
    text = EMOJI_PATTERN.sub("", text)
    text = SPECIAL_CHARS_PATTERN.sub("", text)
    text = MULTI_SPACE_PATTERN.sub(" ", text)
    return text.strip()


class EdgeTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not text.strip():
            return b""

        clean = clean_for_tts(text)
        if not clean:
            self.log.debug(f"⚠️ Text rỗng sau normalize: '{text[:60]}'")
            return b""

        if clean != text.strip():
            self.log.debug(f"🧹 '{text[:60]}' → '{clean[:60]}'")

        voice = kwargs.get("voice") or self.config.get("voice")
        rate = self.config.get("rate", "+0%")
        volume = self.config.get("volume", "+0%")
        timeout = self.config.get("request_timeout", 30.0)
        max_retries = self.config.get("max_retries", 3)

        last_err = None
        for attempt in range(max_retries):
            try:
                start = time.perf_counter()
                mp3 = await asyncio.wait_for(
                    self._synth_once(clean, voice, rate, volume),
                    timeout=timeout,
                )
                elapsed = (time.perf_counter() - start) * 1000
                if mp3:
                    self.log.info(f"🔊 Edge [{elapsed:.0f}ms]: {len(mp3)}b")
                    return mp3
            except asyncio.TimeoutError:
                last_err = f"Timeout {timeout}s"
                self.log.warning(f"⏱️ Edge timeout (lần {attempt + 1})")
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                self.log.warning(f"❌ Edge lỗi (lần {attempt + 1}): {last_err}")

            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))

        self.log.error(f"❌ Edge thất bại: {last_err}")
        return b""

    async def _synth_once(self, text, voice, rate, volume) -> bytes:
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, volume=volume
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)


ProviderRegistry.register_tts("edge", EdgeTTSProvider)
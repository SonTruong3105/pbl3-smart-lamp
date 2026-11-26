"""Text processing utilities — sentence splitting + cleaning."""

import re
from app.config import config

# ═══ SENTENCE SPLITTER ═══
def _is_number_dot(buffer: str, pos: int) -> bool:
    if pos <= 0 or not buffer[pos - 1].isdigit():
        return False
    if pos >= len(buffer) - 1:
        return True
    return buffer[pos + 1].isdigit()


def _find_sentence_end(buffer: str, seps: list) -> tuple:
    earliest_pos, earliest_sep = -1, None
    for sep in seps:
        p = buffer.find(sep)
        while p != -1:
            if sep == "." and _is_number_dot(buffer, p):
                p = buffer.find(sep, p + 1)
                continue
            break
        if p != -1 and (earliest_pos == -1 or p < earliest_pos):
            earliest_pos, earliest_sep = p, sep
    return earliest_pos, earliest_sep


def extract_sentences(buffer: str) -> tuple:
    """Trả về (sentences, buffer_remainder)."""
    sentences = []
    seps = [".", "!", "?", "。", "！", "？"]
    min_len = max(12, int(config.min_sentence_len))
    max_len = max(48, int(config.max_buffer_len))

    while True:
        original_len = len(buffer)
        pos, _ = _find_sentence_end(buffer, seps)
        if pos == -1:
            break
        sentence = buffer[: pos + 1].strip()
        buffer = buffer[pos + 1:].lstrip()
        if len(sentence) >= min_len:
            sentences.append(sentence)
        elif sentences:
            sentences[-1] = f"{sentences[-1]} {sentence}".strip()
        else:
            if sentence:
                buffer = f"{sentence} {buffer}".strip()
            if len(buffer) >= original_len:
                break

    if len(buffer) > max_len:
        comma = buffer.rfind(",", min_len, max_len)
        if comma != -1:
            sentences.append(buffer[: comma + 1].strip())
            buffer = buffer[comma + 1:].lstrip()
        else:
            space = buffer.rfind(" ", min_len, max_len)
            if space != -1:
                sentences.append(buffer[:space].strip())
                buffer = buffer[space + 1:].lstrip()

    return sentences, buffer


# ═══ TEXT CLEANER ═══
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")


def filter_chinese(text: str) -> str:
    if not text:
        return text
    return _CHINESE_RE.sub("", text)


_HARD_BLOCK_COMPILED = [
    re.compile(r"(?i)\bBAD\b"),
    re.compile(r"(?i)(?:system\s+prompt|developer\s+message|function_call|tool_call)"),
]


def _soften_numbers(text: str) -> str:
    text = re.sub(r"(\d+)\.\d+\s*độ\s*C", r"khoảng \1 độ", text)
    text = re.sub(r"(\d+)\.\d+\s*°C", r"khoảng \1 độ", text)
    text = re.sub(r",?\s*\d+\.?\d*\s*km/h", "", text)
    text = re.sub(r",?\s*\(cảm\s+giác[^)]*\)", "", text)
    return text


def clean_response(
    text: str,
    max_sentences: int = 2,
    max_chars: int = 360,
) -> str:
    if not text:
        return text
    if any(p.search(text) for p in _HARD_BLOCK_COMPILED):
        return "Mình không thể thực hiện yêu cầu đó."

    text = filter_chinese(text)
    text = re.sub(r"([.!?。！？])(?=[^\s\d])", r"\1 ", text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [s.strip() for s in sentences if s.strip()]

    result = " ".join(cleaned).strip()
    result = _soften_numbers(result)
    result = re.sub(r"[#*_`>]+", "", result)
    result = re.sub(r"\s+", " ", result).strip()

    if result:
        parts = re.split(r"(?<=[.!?])\s+", result)
        if len(parts) > max_sentences:
            result = " ".join(parts[:max_sentences])
            if not result.rstrip().endswith((".", "!", "?")):
                result = result.rstrip(",;:") + "."

    if len(result) > max_chars:
        shortened = result[:max_chars]
        boundary = max(
            shortened.rfind("."),
            shortened.rfind("!"),
            shortened.rfind("?"),
            shortened.rfind(" "),
        )
        if boundary > max_chars // 2:
            result = shortened[:boundary].rstrip(" ,;:") + "."
        else:
            result = shortened.rstrip(" ,;:") + "…"

    return result or text


def compact_tool_result(text: str, max_chars: int = 400) -> str:
    if not text:
        return ""
    t = str(text).strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    for sep in (".", "!", "?", "\n", ",", " "):
        idx = cut.rfind(sep)
        if idx > max_chars // 2:
            return cut[: idx + 1].strip() + "…"
    return cut + "…"

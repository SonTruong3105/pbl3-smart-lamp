"""Text cleaning cho response LLM → TTS."""
import re

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")


def filter_chinese(text: str) -> str:
    """Loại bỏ ký tự CJK khỏi text."""
    if not text:
        return text
    return _CHINESE_RE.sub("", text)


_HARD_BLOCK_COMPILED = [
    re.compile(r"(?i)\bBAD\b"),
    re.compile(r"(?i)(?:system\s+prompt|developer\s+message|function_call|tool_call)"),
]


def _soften_numbers(text: str) -> str:
    """Chuyển số liệu thành cách nói tự nhiên hơn."""
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
    """Apply safety filtering and light formatting without rewriting natural chat."""
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
    """Rút gọn kết quả tool trước khi đưa vào history/LLM."""
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
"""Tách câu streaming cho TTS."""
from app.config import config


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
    # Chỉ ngắt theo dấu kết thúc câu để TTS đọc liền mạch, tránh băm vụn theo dấu phẩy.
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
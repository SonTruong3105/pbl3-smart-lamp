from app.core.connection import extract_sentences

def test_stream(text: str):
    """Giả lập stream từng ký tự như LLM."""
    buffer = ""
    sentences = []
    for ch in text:
        buffer += ch
        sents, buffer = extract_sentences(buffer)
        sentences.extend(sents)
    if buffer.strip():
        sentences.append(buffer.strip())

    print(f"Input:   {text!r}")
    for i, s in enumerate(sentences, 1):
        print(f"  Câu {i}: {s!r}")
    print()

if __name__ == "__main__":
    test_stream("Nhiệt độ từ 26.0°C đến 31.3°C, mưa 59%.")
    test_stream("Hôm nay 31.3 độ C. Ngày mai 30.5 độ C. Ngày kia 29.8 độ.")
    test_stream("Giá 1.500.000 đồng. Rất đắt.")
    test_stream("Đà Nẵng: 26.0°C - 31.3°C. Hà Nội: 24.5°C - 30.1°C.")
    test_stream("Xin chào. Tôi là trợ lý ảo.")
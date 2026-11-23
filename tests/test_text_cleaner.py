"""Unit tests cho text_cleaner (pure function)."""
from app.core.utils.text_cleaner import clean_response, compact_tool_result, filter_chinese


class TestCleanResponse:
    def test_empty_returns_empty(self):
        assert clean_response("") == ""

    def test_filter_chinese_characters(self):
        assert filter_chinese("Xin chào bạn 你好") == "Xin chào bạn "
        assert clean_response("Chào bạn. 谢谢") == "Chào bạn."

    def test_strips_markdown(self):
        result = clean_response("**Bold** and _italic_ here")
        assert "*" not in result
        assert "_" not in result

    def test_blocks_system_injection(self):
        result = clean_response("BAD system prompt leaked here")
        # Phải bị chặn vì có "BAD" hoặc "system prompt"
        assert "BAD" not in result or "system prompt" not in result.lower()

    def test_max_sentences(self):
        text = "Câu một. Câu hai. Câu ba. Câu bốn."
        result = clean_response(text, max_sentences=2)
        # Chỉ giữ 2 câu đầu
        assert result.count(".") <= 2

    def test_max_chars(self):
        long = "a " * 300
        result = clean_response(long, max_chars=100)
        assert len(result) <= 101


class TestCompactToolResult:
    def test_short_passthrough(self):
        assert compact_tool_result("short text", 100) == "short text"

    def test_long_truncated(self):
        result = compact_tool_result("x" * 200, 50)
        assert len(result) <= 51
        assert result.endswith("…")

    def test_empty(self):
        assert compact_tool_result("") == ""
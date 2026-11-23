"""Unit tests cho sentence_splitter (pure function, không I/O)."""
from app.core.utils.sentence_splitter import _is_number_dot


class TestIsNumberDot:
    def test_digit_before_and_after(self):
        assert _is_number_dot("hello3.14", 6) is True

    def test_no_digit_before(self):
        assert _is_number_dot("hello. world", 5) is False

    def test_dot_at_end(self):
        assert _is_number_dot("3.", 1) is True

    def test_not_digit_at_pos_minus_1(self):
        # ".5" → char trước dấu . là đầu chuỗi (pos=0)
        assert _is_number_dot(".5", 0) is False
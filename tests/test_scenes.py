"""Unit tests cho scenes (pure parsing/match logic)."""
from app.core.providers.tools.scenes import _match_scene, _parse_time_str


class TestMatchScene:
    def test_direct_match(self):
        assert _match_scene("đọc sách") == "doc sach"

    def test_substring_match(self):
        assert _match_scene("tôi muốn đọc sách bây giờ") == "doc sach"

    def test_alias_match(self):
        assert _match_scene("đi ngủ") == "ngu"
        assert _match_scene("xem phim") == "phim"

    def test_unknown_returns_none(self):
        assert _match_scene("xyz abc") is None

    def test_empty_returns_none(self):
        assert _match_scene("") is None
        assert _match_scene(None) is None


class TestParseTime:
    def test_basic_hour(self):
        assert _parse_time_str("7 giờ") == (7, 0)

    def test_hour_colon_minute(self):
        assert _parse_time_str("19:30") == (19, 30)

    def test_evening_keyword(self):
        assert _parse_time_str("7 giờ tối") == (19, 0)

    def test_morning_12_is_zero(self):
        assert _parse_time_str("12 giờ sáng") == (0, 0)

    def test_invalid_returns_none(self):
        assert _parse_time_str("không có giờ") is None
        assert _parse_time_str("") is None
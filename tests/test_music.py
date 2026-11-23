from app.music import extract_video_id, music_search_query


def test_extract_video_id_from_youtube_urls_and_transcripts():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("Mở https://www.youtube.com/watch?v=dQw4w9WgXcQ nhé") == "dQw4w9WgXcQ"
    assert extract_video_id("not a video id") is None


def test_music_search_query_removes_voice_playback_phrasing():
    assert music_search_query("Mở nhạc Sơn Tùng nhé") == "Sơn Tùng"
    assert music_search_query('Phát bài hát “Nơi này có anh” trên YouTube') == "Nơi này có anh"
    assert music_search_query("nhạc chill") == "chill"
    assert music_search_query("   ") is None

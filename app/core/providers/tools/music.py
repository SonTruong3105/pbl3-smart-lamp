"""Music tool — port từ AI Chatbot (YouTube resolver + cache)."""
from loguru import logger

from app.core.providers.tools.unified.register import (
    Action, ActionResponse, register_function)
from app.core.providers.tools.context import get_connection
from app.music import (
    MusicError, extract_video_id, get_cache, music_search_query,
    resolve_ogg, search_youtube,
)


_GENERIC_MUSIC_FALLBACKS = {
    "nhạc": "nhạc Việt hot 2024",
    "bài": "nhạc Việt hot 2024",
    "bài hát": "nhạc Việt hot 2024",
    "music": "nhạc Việt hot 2024",
    "youtube": "nhạc Việt hot 2024",
    "nhạc nhẹ": "nhạc chill acoustic",
    "nhạc nhẹ nhàng": "nhạc chill acoustic",
    "nhẹ": "nhạc chill acoustic",
    "nhẹ nhàng": "nhạc chill acoustic",
    "êm dịu": "nhạc chill acoustic",
    "nhạc buồn": "nhạc buồn tâm trạng Việt",
    "buồn": "nhạc buồn tâm trạng Việt",
    "nhạc vui": "nhạc vui Việt Nam",
    "vui": "nhạc vui Việt Nam",
    "nhạc chill": "lofi chill Việt",
    "chill": "lofi chill Việt",
    "lofi": "lofi hiphop chill",
    "nhạc việt": "nhạc Việt hot 2024",
    "nhạc trẻ": "nhạc trẻ Việt hot",
    "nhạc thiền": "nhạc thiền thư giãn",
    "nhạc piano": "piano relaxing",
    "nhạc tết": "nhạc Tết remix",
    "nhạc sôi động": "nhạc remix Việt hot",
    "sôi động": "nhạc remix Việt hot",
    "nhạc học bài": "lofi study chill",
    "học bài": "lofi study chill",
    "nhạc ngủ": "nhạc ngủ thiền",
    "ngủ": "nhạc ngủ thiền",
    "ngủ ngon": "nhạc ngủ thiền",
    "một bài": "nhạc Việt hot 2024",
    "bài gì đó": "nhạc Việt hot 2024",
    "bài gì cũng được": "nhạc Việt hot 2024",
    "gì cũng được": "nhạc Việt hot 2024",
    "sao cũng được": "nhạc Việt hot 2024",
}


def _normalize_music_query(query):
    if not query:
        return query
    q = query.lower().strip()
    return _GENERIC_MUSIC_FALLBACKS.get(q, query)


@register_function(
    name="play_music",
    description=(
        "Phát nhạc từ YouTube. User nói cụ thể thì truyền đúng tên. "
        "User nói chung chung (nhạc, nhạc nhẹ, nhạc chill, nhạc buồn) "
        "thì TỰ CHỌN query cụ thể (VD: 'nhạc Việt hot 2024'). "
        "KHÔNG hỏi lại — chọn và phát luôn."
    ),
    parameters={"query": {"type": "string", "required": True}},
)
async def play_music(query: str) -> ActionResponse:
    conn = get_connection()
    if conn is None:
        return ActionResponse(Action.ERROR, result="Không có connection.")

    _orig = query
    video_id = extract_video_id(query)
    if video_id:
        query = video_id
    else:
        query = music_search_query(query) or query
        query = _normalize_music_query(query)
    if query != _orig:
        logger.info(f"🎵 Query normalize: {_orig!r} → {query!r}")

    async def _status(stage, label=""):
        try:
            await conn._send_callback({"type": "music_status", "stage": stage, "label": label})
        except Exception:
            pass

    try:
        await _status("searching", query)
        cache = get_cache()
        vid = query if video_id else await search_youtube(query)
        if not vid:
            await _status("error", query)
            return ActionResponse(Action.ERROR, result=f"Không tìm thấy '{query}'.")
        audio = cache.get(vid)
        if audio is None:
            await _status("downloading", query)
            audio = await resolve_ogg(vid)
            logger.info(f"🎵 Music downloaded: video={vid} bytes={len(audio)}")
        else:
            logger.info(f"🎵 Music cache hit: video={vid} bytes={len(audio)}")
    except MusicError as e:
        await _status("error", query)
        return ActionResponse(Action.ERROR, result=str(e))
    except Exception as e:
        await _status("error", query)
        logger.exception(f"play_music: {e}")
        return ActionResponse(Action.ERROR, result="Không phát được nhạc.")
    await _status("ready", query)

    # ESP32 plays Opus frames, so hand the source audio to its connection handler.
    if hasattr(conn, "opus"):
        conn._pending_music = {"audio": audio, "label": query}
        text = f"Đang phát: {query}."
        return ActionResponse(Action.RESPONSE, result=text, response=text)

    # Browser clients play the cached track through a static URL.
    import os
    import uuid
    filename = f"{vid}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = os.path.join("static", "music", filename)
    with open(filepath, "wb") as f: f.write(audio)
        
    url = f"/static/music/{filename}"
    await conn._send_callback({"type": "music_meta", "label": query, "url": url})
    logger.info(f"🎵 Music saved & queued: {query!r} -> {url} ({len(audio)} bytes)")
    text = f"Đang phát: {query}."
    # [PATCH P4] Trả response thật — tránh assistant history rỗng
    return ActionResponse(Action.RESPONSE, result=text, response=text)
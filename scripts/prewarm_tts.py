"""prewarm_tts.py — Synthesize sẵn các câu phổ biến vào cache TTS.

Chạy SAU khi server đã sẵn sàng (VieNeu 11436 đang up):
    python prewarm_tts.py

Hoặc tự động từ run.py sau warmup (xem docs).
"""
import asyncio
import sys
from app.config import config
from app.core.providers.base import ProviderRegistry
from app.core.providers.tts import vieneu, edge  # noqa
from app.core.utils.tts_cache import get_cache


PREWARM_PHRASES = [
    # Greetings
    "Chào bạn!", "Ơi chào bạn!", "Chào bạn, mình nghe nè!",
    "Dạ em đây!", "Hế lô, chào bạn!",
    # Device confirmations
    "Đèn bật rồi nha!", "Đèn tắt rồi đó bạn.",
    "Đã điều chỉnh độ sáng.", "Đã chuyển màu đèn.",
    "Đã chuyển chế độ đọc sách.", "Đã chuyển chế độ ngủ.",
    "Đã chuyển chế độ làm việc.",
    # Errors
    "Đèn chưa kết nối, mình không bật được.",
    "Đèn chưa kết nối, mình không tắt được.",
    "Mình không hiểu ý bạn.",
    # Time
    "Để mình xem giờ cho bạn nhé.",
]


async def main():
    tts = ProviderRegistry.create_tts(
        config.tts_provider,
        config={
            "voice": config.tts_voice,
            "url": config.tts_vieneu_url,
            "request_timeout": config.tts_request_timeout,
            "max_retries": 1,
        },
    )
    cache = get_cache()
    voice = config.tts_voice
    ok = 0
    for phrase in PREWARM_PHRASES:
        if cache.get(phrase, voice):
            print(f"OK    {phrase!r}")
            ok += 1
            continue
        try:
            audio = await asyncio.wait_for(tts.synthesize(phrase), timeout=10.0)
            if audio:
                cache.put(phrase, audio, voice)
                print(f"NEW   {phrase!r} ({len(audio)}b)")
                ok += 1
            else:
                print(f"EMPTY {phrase!r}")
        except Exception as e:
            print(f"FAIL  {phrase!r}: {e}")
    print(f"\n{ok}/{len(PREWARM_PHRASES)} phrases cached")


if __name__ == "__main__":
    asyncio.run(main())
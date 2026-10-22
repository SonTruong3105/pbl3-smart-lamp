"""Đo toàn pipeline: ASR → LLM → TTS (VietVoice)."""
import asyncio
import time
import sys
from pathlib import Path

# Thêm project root vào sys.path để import được app
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from app.ai.tts_local import synthesize_local


ASR_URL = "http://localhost:11435/v1/audio/transcriptions"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b"


async def step_asr(wav_path: str) -> tuple[str, float]:
    """Bước ASR."""
    if not Path(wav_path).exists():
        print(f"⚠️  Không có {wav_path}, dùng text mặc định")
        return "Thời tiết Đà Nẵng hôm nay thế nào?", 0.0

    with open(wav_path, "rb") as f:
        audio = f.read()

    async with httpx.AsyncClient(timeout=60) as client:
        start = time.perf_counter()
        r = await client.post(
            ASR_URL,
            files={"file": ("audio.wav", audio, "audio/wav")},
            data={"language": "vi"},
        )
        elapsed = time.perf_counter() - start
        text = r.json().get("text", "")
        print(f"📝 ASR [{elapsed*1000:.0f}ms]: {text}")
        return text, elapsed


async def step_llm(prompt: str) -> tuple[str, float]:
    """Bước LLM."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 150},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        start = time.perf_counter()
        r = await client.post(OLLAMA_URL, json=payload)
        elapsed = time.perf_counter() - start
        response = r.json().get("message", {}).get("content", "")
        print(f"🤖 LLM [{elapsed*1000:.0f}ms]: {response[:80]}")
        return response, elapsed


async def step_tts(text: str) -> tuple[bytes, float]:
    """Bước TTS — VietVoice local."""
    start = time.perf_counter()
    wav_bytes = await synthesize_local(text)
    elapsed = time.perf_counter() - start
    print(f"🔊 TTS [{elapsed*1000:.0f}ms]: {len(wav_bytes)} bytes")
    return wav_bytes, elapsed


async def main():
    print("=" * 60)
    print("ĐO TOÀN PIPELINE")
    print("=" * 60)
    print()

    wav_path = sys.argv[1] if len(sys.argv) > 1 else "test.wav"

    # ASR
    user_text, asr_time = await step_asr(wav_path)
    print()

    # LLM
    response, llm_time = await step_llm(user_text)
    print()

    # TTS
    audio, tts_time = await step_tts(response)
    print()

    # Tổng
    total = asr_time + llm_time + tts_time
    print("=" * 60)
    print("KẾT QUẢ")
    print("=" * 60)
    if total > 0:
        print(f"ASR:  {asr_time*1000:>6.0f}ms  ({asr_time/total*100:.0f}%)")
        print(f"LLM:  {llm_time*1000:>6.0f}ms  ({llm_time/total*100:.0f}%)")
        print(f"TTS:  {tts_time*1000:>6.0f}ms  ({tts_time/total*100:.0f}%)")
        print("-" * 60)
        print(f"TỔNG: {total*1000:>6.0f}ms")
    print()
    if total < 2:
        print("✅ XUẤT SẮC (< 2s)")
    elif total < 3:
        print("✅ TỐT (2-3s)")
    elif total < 5:
        print("⚠️  CHẤP NHẬN ĐƯỢC (3-5s)")
    else:
        print("❌ CHẬM (> 5s) — cần tối ưu")


if __name__ == "__main__":
    asyncio.run(main())
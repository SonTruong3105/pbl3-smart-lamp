"""Đo tốc độ ASR (PhoWhisper)."""
import asyncio
import time
import httpx
from pathlib import Path


ASR_URL = "http://localhost:11435/v1/audio/transcriptions"


async def measure_asr(wav_path: str, runs: int = 3):
    """Đo ASR N lần, in từng lần + trung bình."""
    if not Path(wav_path).exists():
        print(f"❌ Không tìm thấy: {wav_path}")
        return

    with open(wav_path, "rb") as f:
        audio = f.read()

    print(f"📁 File: {wav_path} ({len(audio)} bytes)")
    print(f"🔄 Chạy {runs} lần\n")

    times = []
    for i in range(runs):
        async with httpx.AsyncClient(timeout=60) as client:
            start = time.perf_counter()
            r = await client.post(
                ASR_URL,
                files={"file": ("audio.wav", audio, "audio/wav")},
                data={"language": "vi"},
            )
            elapsed = time.perf_counter() - start

            if r.status_code != 200:
                print(f"❌ Lần {i+1}: HTTP {r.status_code} - {r.text[:100]}")
                continue

            text = r.json().get("text", "")
            times.append(elapsed)
            print(f"✅ Lần {i+1}: {elapsed*1000:.0f}ms → {text}")

    if times:
        print(f"\n📊 Trung bình: {sum(times)/len(times)*1000:.0f}ms")
        print(f"📊 Nhanh nhất: {min(times)*1000:.0f}ms")
        print(f"📊 Chậm nhất: {max(times)*1000:.0f}ms")


if __name__ == "__main__":
    import sys

    wav_path = sys.argv[1] if len(sys.argv) > 1 else "test.wav"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    asyncio.run(measure_asr(wav_path, runs))
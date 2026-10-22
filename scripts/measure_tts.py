import asyncio
import time
import edge_tts


async def measure(text: str):
    start = time.perf_counter()
    communicate = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural")
    audio = bytearray()
    first_chunk = None

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            if first_chunk is None:
                first_chunk = time.perf_counter() - start
            audio.extend(chunk["data"])

    total = time.perf_counter() - start
    print(f"📝 '{text[:50]}'")
    print(f"   First: {first_chunk*1000:.0f}ms | Total: {total*1000:.0f}ms | Size: {len(audio)} bytes\n")


async def main():
    print("=" * 60)
    await measure("Xin chào")
    await measure("Đà Nẵng hôm nay có mưa nhẹ, nhiệt độ 25°C.")
    await measure("Đà Nẵng hôm nay có mưa nhẹ rải rác, nhiệt độ 25°C, độ ẩm 92%, gió 9 km/h.")


asyncio.run(main())
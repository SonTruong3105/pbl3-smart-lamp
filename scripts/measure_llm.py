"""Đo tốc độ LLM (Ollama)."""
import asyncio
import time
import httpx


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b"


async def measure_llm(prompt: str, runs: int = 3, stream: bool = False):
    """Đo LLM N lần."""
    print(f"📝 Prompt: {prompt}")
    print(f"🤖 Model: {MODEL}")
    print(f"🔄 Chạy {runs} lần | Stream: {stream}\n")

    times = []
    for i in range(runs):
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "think": False,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            start = time.perf_counter()

            if stream:
                first_token_time = None
                full_text = ""
                async with client.stream("POST", OLLAMA_URL, json=payload) as r:
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        import json
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                if first_token_time is None:
                                    first_token_time = time.perf_counter() - start
                                full_text += token
                        except Exception:
                            pass

                elapsed = time.perf_counter() - start
                times.append(first_token_time)
                print(f"✅ Lần {i+1}: first={first_token_time*1000:.0f}ms | total={elapsed*1000:.0f}ms")
                print(f"   → {full_text[:80]}")
            else:
                r = await client.post(OLLAMA_URL, json=payload)
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                text = r.json().get("message", {}).get("content", "")
                print(f"✅ Lần {i+1}: {elapsed*1000:.0f}ms")
                print(f"   → {text[:80]}")

    if times:
        print(f"\n📊 Trung bình: {sum(times)/len(times)*1000:.0f}ms")
        print(f"📊 Nhanh nhất: {min(times)*1000:.0f}ms")
        print(f"📊 Chậm nhất: {max(times)*1000:.0f}ms")


if __name__ == "__main__":
    import sys

    prompt = sys.argv[1] if len(sys.argv) > 1 else "Xin chào, bạn là ai?"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    stream = "--stream" in sys.argv

    asyncio.run(measure_llm(prompt, runs, stream))
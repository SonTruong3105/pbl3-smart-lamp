"""Test ASYNC httpx — giống hệt backend."""
import asyncio
import sys
import httpx
import time
import json

# Force Selector policy (giống main.py)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def test():
    sys_prompt = "Ban la tro ly ao tieng Viet. Tra loi ngan gon."
    
    tools = [
        {"type":"function","function":{"name":"get_weather","description":"Tra thoi tiet.","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}},
        {"type":"function","function":{"name":"web_search","description":"Tim web.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    ]
    
    payload = {
        "model": "qwen3.5:2b",
        "messages": [
            {"role":"system","content":sys_prompt},
            {"role":"user","content":"chao"},
        ],
        "stream": True,
        "think": False,
        "options": {"temperature": 0.6, "num_predict": 180},
        "tools": tools,
    }
    
    sw = time.perf_counter()
    first = None
    n = 0
    content = ""
    
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", "http://localhost:11434/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip(): continue
                n += 1
                if first is None: first = time.perf_counter() - sw
                try:
                    d = json.loads(line)
                    tok = d.get("message", {}).get("content", "")
                    content += tok
                    if n <= 3: print(f"[{n}] {line[:120]}")
                except Exception:
                    pass
    
    print(f"---")
    print(f"Total: {n} lines, first: {first:.2f}s, total: {time.perf_counter()-sw:.2f}s")
    print(f"Content: {content[:150]!r}")


if __name__ == "__main__":
    asyncio.run(test())

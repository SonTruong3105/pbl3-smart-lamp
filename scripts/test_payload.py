"""Test payload giống backend gửi."""
import httpx, time, json

sys_prompt = """Ban la tro ly ao tieng Viet than thien.
QUY TAC: KHONG markdown. Viet ngan gon.
VI DU: User: 'Xin chao' -> 'Chao ban!'"""

tools = [
    {"type":"function","function":{"name":"get_weather","description":"Tra thoi tiet.","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}},
    {"type":"function","function":{"name":"get_forecast","description":"Du bao nhieu ngay.","parameters":{"type":"object","properties":{"city":{"type":"string"},"days":{"type":"integer"}},"required":["city"]}}},
    {"type":"function","function":{"name":"web_search","description":"Tim web.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_current_time","description":"Gio hien tai.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"get_weekday","description":"Thu cua ngay.","parameters":{"type":"object","properties":{"date":{"type":"string"}},"required":["date"]}}},
]

payload = {
    "model": "qwen3.5:2b",
    "messages": [
        {"role":"system","content":sys_prompt},
        {"role":"user","content":"chao"}
    ],
    "stream": True,
    "think": False,
    "options": {"temperature": 0.6, "num_predict": 180},
    "tools": tools,
}

sw = time.perf_counter()
with httpx.Client(timeout=60) as c:
    with c.stream("POST","http://localhost:11434/api/chat", json=payload) as r:
        r.raise_for_status()
        n=0; first=None; content=""
        for line in r.iter_lines():
            if not line.strip(): continue
            n+=1
            if first is None: first = time.perf_counter()-sw
            try:
                d=json.loads(line)
                tok=d.get("message",{}).get("content","")
                content+=tok
                if n<=5: print(f"[{n}] {line[:100]}")
            except: pass
        print("---")
        print(f"Total: {n} lines, first: {first:.2f}s, total: {time.perf_counter()-sw:.2f}s")
        print(f"Content: {content[:150]!r}")

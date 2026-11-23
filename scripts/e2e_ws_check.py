import asyncio
import json
import urllib.request
import websockets

WS_URI = "ws://127.0.0.1:8000/ws/chat"
HTTP_BASE = "http://127.0.0.1:8000"
DEVICE_ID = "e2e-check-device-01"


async def send_and_collect(ws, text: str, timeout: float = 25.0) -> str:
    await ws.send(json.dumps({"type": "message", "text": text}, ensure_ascii=False))
    parts = []
    async with asyncio.timeout(timeout):
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "token":
                parts.append(msg.get("content", ""))
            elif mtype == "error":
                raise RuntimeError(f"Server error for '{text}': {msg.get('text')}")
            elif mtype == "end":
                break
    return "".join(parts).strip()


async def main():
    async with websockets.connect(WS_URI) as ws:
        await ws.send(json.dumps({
            "type": "hello",
            "device_id": DEVICE_ID,
            "session_id": None,
            "force_new": False,
        }))
        init_msg = json.loads(await ws.recv())
        print("[1] Init:", init_msg)
        session_id = init_msg["session_id"]

        prompts = [
            "Chào bạn, hôm nay mình hơi mệt một chút.",
            "Bây giờ là mấy giờ rồi?",
            "Kiểm tra bụi mịn PM2.5 giúp mình nhé",
        ]
        for q in prompts:
            ans = await send_and_collect(ws, q)
            print(f"    Q: {q}\n    A: {ans}\n")

    await asyncio.sleep(0.5)

    async with websockets.connect(WS_URI) as ws2:
        await ws2.send(json.dumps({
            "type": "hello",
            "device_id": DEVICE_ID,
            "session_id": session_id,
            "force_new": False,
        }))
        resume_msg = json.loads(await ws2.recv())
        print("[2] Resume:", resume_msg)
        assert resume_msg["session_id"] == session_id, "Session ID không giữ nguyên khi resume"

    with urllib.request.urlopen(f"{HTTP_BASE}/api/sessions/{session_id}/messages", timeout=10) as resp:
        hist = json.loads(resp.read().decode("utf-8"))
    print(f"[3] Saved messages count: {len(hist.get('messages', []))}")
    for m in hist.get("messages", [])[-4:]:
        print(f"    - {m['role']}: {m['content']}")


if __name__ == "__main__":
    asyncio.run(main())

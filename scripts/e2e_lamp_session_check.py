import asyncio
import json
import websockets

WS_URI = "ws://127.0.0.1:8000/ws/chat"
WEB_DEVICE_ID = "e2e-lamp-check-01"
ESP32_DEVICE_ID = "esp32-lamp-01"  # Đổi sang ID ESP32 thực tế nếu đã kết nối


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
                return f"[ERROR] {msg.get('text')}"
            elif mtype == "end":
                break
    return "".join(parts).strip()


async def main():
    async with websockets.connect(WS_URI) as ws:
        # 1. Yêu cầu tạo session mới hoàn toàn với force_new=True
        await ws.send(json.dumps({
            "type": "hello",
            "device_id": WEB_DEVICE_ID,
            "session_id": None,
            "force_new": True,
        }))
        init_msg = json.loads(await ws.recv())
        print("[1] Force New Session:", init_msg)
        assert init_msg.get("is_new") is True, "Kỳ vọng is_new=True khi force_new=True"

        # 2. Kiểm tra xưng hô & độ tự nhiên trên session sạch
        for q in [
            "Hôm nay trời hơi oi bức, mình làm việc hơi mệt.",
            "Bật đèn bàn giúp mình nhé",
        ]:
            ans = await send_and_collect(ws, q)
            print(f"    Q: {q}\n    A: {ans}\n")

        # 3. Kiểm tra link tới ESP32 (nếu ESP32 chưa online sẽ trả thông báo lỗi rõ ràng)
        await ws.send(json.dumps({
            "type": "link",
            "esp32_device_id": ESP32_DEVICE_ID,
        }))
        async with asyncio.timeout(10.0):
            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") in ("link_status", "error"):
                    link_resp = msg
                    break
        print("[3] Link ESP32 response:", link_resp)

        # 4. Gửi thử lamp_state nếu đã link thành công
        if link_resp.get("type") == "link_status" and link_resp.get("linked"):
            await ws.send(json.dumps({
                "type": "lamp_state",
                "on": True,
                "brightness": 75,
                "cct": 4000,
            }))
            print("    Sent lamp_state (on=True, brightness=75, cct=4000K)")
            await asyncio.sleep(0.5)
            await ws.send(json.dumps({"type": "unlink"}))
            print("    Unlink resp:", json.loads(await ws.recv()))


if __name__ == "__main__":
    asyncio.run(main())

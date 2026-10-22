import asyncio
import json
import websockets

async def test():
    url = "ws://192.168.1.19:8000/xiaozhi/v1/"

    # ✅ websockets v12+ dùng additional_headers
    # Nếu version cũ hơn (<12) dùng extra_headers
    try:
        # Thử API mới
        ws = await websockets.connect(
            url,
            additional_headers={"Device-Id": "TEST-PC-001"},
        )
    except TypeError:
        # Fallback API cũ
        ws = await websockets.connect(
            url,
            extra_headers={"Device-Id": "TEST-PC-001"},
        )

    async with ws:
        # 1. Gửi hello
        await ws.send(json.dumps({
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        }))

        # 2. Nhận hello response
        resp = await ws.recv()
        print("← Server:", resp)

        data = json.loads(resp)
        if data.get("session_id"):
            print(f"✅ BACKEND OK — session_id = {data['session_id']}")
        else:
            print("❌ BACKEND LỖI — không có session_id")

        # 3. Đóng gọn gàng
        await ws.close()

asyncio.run(test())
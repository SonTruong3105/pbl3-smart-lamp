"""Test end-to-end qua /ws/chat. Chạy: python scripts/test_suite.py"""
import asyncio, json, time, sys
import websockets
from websockets.exceptions import ConnectionClosed

WS_URL = "ws://localhost:8000/ws/chat"
DEVICE_ID = "test-suite-pc"

# (name, prompt, [must_contain], max_latency_s, timeout_s)
CASES = [
    # FAST TRACK (< 2s)
    ("greeting",   "Xin chào",                 ["chào"],       2.0,  15.0),
    ("hello",      "hello",                    ["chào"],       2.0,  15.0),
    ("thanks",     "Cảm ơn nhé",               ["không", "gì"],2.0,  15.0),
    ("time",       "Mấy giờ rồi",              ["giờ"],        2.0,  15.0),
    ("weekday",    "Hôm nay thứ mấy",          ["thứ"],        3.5,  15.0),
    ("date",       "Hôm nay ngày mấy",         ["ngày"],       3.5,  15.0),
    ("math_add",   "Tính 2 cộng 3",            ["5"],          2.0,  15.0),
    ("math_mul",   "5 nhân 8",                 ["40"],         2.0,  15.0),
    ("math_div",   "Tính (10+5) chia 3",       ["5"],          2.5,  15.0),
    ("math_deci",  "Tính 2 phẩy 5 nhân 2",     ["5"],          2.5,  15.0),

    # TOOL DEVICE — không có ESP32 → trả "chưa có dữ liệu"
    ("lamp_on",    "Bật đèn",                  ["đèn"],        4.0,  15.0),
    ("lamp_off",   "Tắt đèn",                  ["đèn"],        4.0,  15.0),
    ("sensor_all", "Báo cáo phòng",            None,           15.0, 20.0),
    ("sensor_temp","Nhiệt độ phòng",           None,           10.0, 20.0),
    ("air_quality","Không khí thế nào",        None,           10.0, 20.0),

    # SEARCH/WEATHER (< 15s)
    ("weather_hn", "Thời tiết Hà Nội",         ["hà nội"],     12.0, 20.0),
    ("weather_dn", "Đà Nẵng có mưa không",     ["đà nẵng"],    12.0, 20.0),
    ("forecast",   "Dự báo Hà Nội 3 ngày",     ["hà nội"],     12.0, 20.0),
    ("exchange",   "Tỷ giá USD",               ["usd"],        12.0, 20.0),
    ("lunar",      "Hôm nay âm lịch ngày mấy", ["âm"],         10.0, 20.0),

    # LLM CHAT (< 15s)
    ("who_r_u",    "Bạn là ai",                None,           10.0, 20.0),
    ("story",      "Kể chuyện ngắn",           None,           15.0, 25.0),
    ("why",        "Tại sao trời mưa",         None,           15.0, 25.0),

    # ANTI-PATTERN
    ("negation",   "Đừng bật đèn",             None,           10.0, 20.0),
    ("empty_ask",  "Không cần biết",           None,           10.0, 20.0),
]


async def run_one(ws, name, prompt, expect, max_lat, timeout_s):
    t0 = time.perf_counter()
    try:
        await ws.send(json.dumps({"type": "message", "text": prompt}))
    except Exception as e:
        print(f"   ❌ {name}: send lỗi: {type(e).__name__}: {e}")
        return False

    tokens = []
    end_time = t0 + timeout_s
    got_end = False
    got_token = False

    while time.perf_counter() < end_time:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        except asyncio.TimeoutError:
            # Chưa có token nào và đã chờ > 1s → có thể server đang xử lý
            if got_end:
                break
            continue
        except ConnectionClosed as e:
            lat = time.perf_counter() - t0
            print(f"   ❌ {name}: WS close ({lat:.1f}s) — {e}")
            return False
        except Exception as e:
            lat = time.perf_counter() - t0
            print(f"   ❌ {name}: recv lỗi ({lat:.1f}s): {type(e).__name__}: {e}")
            return False

        if isinstance(raw, bytes):
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue

        mtype = msg.get("type")
        if mtype == "token":
            tokens.append(msg.get("content", ""))
            got_token = True
        elif mtype == "end":
            got_end = True
            break
        elif mtype == "error":
            lat = time.perf_counter() - t0
            print(f"   ❌ {name}: error={msg.get('text')!r} ({lat:.1f}s)")
            return False
        # tool, stt, status, audio_meta → bỏ qua, không ảnh hưởng

    lat = time.perf_counter() - t0
    resp = "".join(tokens).strip()

    if not resp:
        print(f"   ❌ {name}: EMPTY ({lat:.1f}s, got_end={got_end})")
        return False
    if lat > max_lat:
        print(f"   ❌ {name}: {lat:.1f}s > {max_lat}s | {resp[:50]!r}")
        return False
    if expect:
        for n in expect:
            if n.lower() not in resp.lower():
                print(f"   ❌ {name}: thiếu '{n}' | {resp[:60]!r}")
                return False
    print(f"   ✅ {name}: {lat:.2f}s | {resp[:60]!r}")
    return True


async def main():
    print(f"🧪 Test suite → {WS_URL}")
    try:
        async with websockets.connect(
            WS_URL,
            additional_headers={"Device-Id": DEVICE_ID},
            open_timeout=10,
            ping_interval=None,        # ← tắt ping phía client luôn
        ) as ws:
            await ws.send(json.dumps({
                "type": "hello", "device_id": DEVICE_ID, "session_id": None,
            }))
            await asyncio.wait_for(ws.recv(), timeout=10)
            print("=" * 72)
            passed = 0
            failed_cases = []
            for c in CASES:
                try:
                    if await run_one(ws, *c):
                        passed += 1
                    else:
                        failed_cases.append(c[0])
                except ConnectionClosed as e:
                    print(f"   ❌ {c[0]}: WS đóng — dừng test")
                    failed_cases.append(c[0])
                    failed_cases.extend(x[0] for x in CASES[CASES.index(c)+1:])
                    break
            print("=" * 72)
            total = len(CASES)
            pct = passed / total * 100
            print(f"📊 {passed}/{total} passed ({pct:.0f}%)")
            if failed_cases:
                print(f"❌ Fail ({len(failed_cases)}): {', '.join(failed_cases)}")
            sys.exit(0 if passed == total else 1)
    except Exception as e:
        print(f"❌ Không kết nối được: {type(e).__name__}: {e}")
        print(f"   👉 Server đã chạy chưa? (python run.py)")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
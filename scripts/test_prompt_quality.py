"""Smoke-evaluate Vietnamese assistant prompt over the live /ws/chat endpoint.

Safe prompts only: this script does not ask the assistant to control devices.
Run from project root: python scripts/test_prompt_quality.py [ws://127.0.0.1:8000/ws/chat]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import websockets
from websockets.exceptions import ConnectionClosed


WS_URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8000/ws/chat"
DEVICE_ID = f"prompt-eval-{uuid.uuid4().hex[:10]}"
CASES = [
    ("greeting", "Xin chào, hôm nay mình hơi mệt.", ("chào",)),
    ("empathetic follow-up", "Mình vừa học cả ngày, giờ muốn nghỉ một chút.", ()),
    ("simple explanation", "Vì sao sau cơn mưa thường có mùi đất?", ()),
    ("capabilities", "Bạn có thể giúp mình những việc gì?", ()),
]


async def run_case(ws, name: str, prompt: str, required: tuple[str, ...]):
    started = time.perf_counter()
    await ws.send(json.dumps({"type": "message", "text": prompt}, ensure_ascii=False))
    tokens: list[str] = []
    errors: list[str] = []
    saw_end = False
    while time.perf_counter() - started < 80:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=25)
        except asyncio.TimeoutError:
            print(f"[{name}] still processing ({time.perf_counter()-started:.1f}s)")
            continue
        except ConnectionClosed as exc:
            return {"name": name, "ok": False, "error": f"WebSocket closed: {exc}"}
        if isinstance(raw, bytes):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "token":
            tokens.append(event.get("content", ""))
        elif kind == "error":
            errors.append(event.get("text", "unknown error"))
        elif kind == "end":
            saw_end = True
            break

    response = "".join(tokens).strip()
    lowered = response.casefold()
    missing = [phrase for phrase in required if phrase.casefold() not in lowered]
    ok = bool(response) and saw_end and not errors and not missing
    elapsed = time.perf_counter() - started
    print(f"[{name}] {'PASS' if ok else 'CHECK'} · {elapsed:.2f}s")
    print(f"  User: {prompt}")
    print(f"  AI:   {response or '<empty response>'}")
    if errors:
        print(f"  Errors: {errors}")
    if missing:
        print(f"  Missing expected phrase(s): {missing}")
    return {"name": name, "ok": ok, "response": response, "elapsed": elapsed}


async def main():
    print(f"Prompt evaluation against {WS_URL}")
    print("Safety scope: conversational prompts only; no device-control requests.\n")
    results = []
    async with websockets.connect(WS_URL, open_timeout=10, ping_interval=None) as ws:
        await ws.send(json.dumps({
            "type": "hello", "device_id": DEVICE_ID,
            "session_id": None, "force_new": True,
        }))
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if hello.get("type") != "session":
            raise RuntimeError(f"Unexpected session handshake: {hello}")
        print(f"Session #{hello.get('session_id')} · device={DEVICE_ID}\n")
        for name, prompt, required in CASES:
            results.append(await run_case(ws, name, prompt, required))
    passed = sum(1 for result in results if result["ok"])
    print(f"\nTransport/response checks: {passed}/{len(results)} passed.")
    print("Naturalness and factual quality still require a human reading the outputs above.")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

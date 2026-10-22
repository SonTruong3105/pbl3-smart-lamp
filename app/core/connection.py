"""ConnectionHandler — xử lý vòng đời 1 WebSocket, TTS song song."""
import asyncio
import re
import time
from typing import Optional

from fastapi import WebSocket

from app.config import config
from app.core.logger import get_session_logger
from app.core.utils.dialogue import Dialogue, Message
from app.core.providers.base import ProviderRegistry

from app.core.providers.asr import phowhisper           # noqa
from app.core.providers.llm import ollama               # noqa
from app.core.providers.tts import edge, piper, vieneu  # noqa
from app.core.providers.memory import local, none       # noqa
from app.core.providers.tools.registry import TOOLS_SCHEMA
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio import any_to_wav


def _clean_response(text: str) -> str:
    """Cắt các câu hỏi ngược lại mà model nhỏ hay chèn vào."""
    if not text:
        return text

    BAD_PATTERNS = [
        r"(?i)bạn\s+cần\s+(giúp|hỗ\s+trợ|gì)",
        r"(?i)mình\s+có\s+thể\s+giúp\s+gì",
        r"(?i)tôi\s+có\s+thể\s+giúp\s+gì",
        r"(?i)cần\s+giúp\s+đỡ\s+gì",
        r"(?i)bạn\s+cần\s+tôi\s+giúp",
        r"(?i)hôm\s+nay\s+(bạn\s+)?cần\s+gì",
        r"(?i)có\s+gì\s+mình\s+giúp\s+được",
        r"(?i)bạn\s+muốn\s+mình\s+giúp\s+gì",
    ]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = []
    for s in sentences:
        s_stripped = s.strip()
        if not s_stripped:
            continue
        if any(re.search(p, s_stripped) for p in BAD_PATTERNS):
            continue
        cleaned.append(s_stripped)

    result = " ".join(cleaned).strip()
    return result if result else text


def _is_number_dot(buffer: str, pos: int) -> bool:
    if pos <= 0:
        return False
    if not buffer[pos - 1].isdigit():
        return False
    if pos >= len(buffer) - 1:
        return True
    return buffer[pos + 1].isdigit()


def _find_sentence_end(buffer: str, seps: list) -> tuple:
    earliest_pos, earliest_sep = -1, None
    for sep in seps:
        p = buffer.find(sep)
        while p != -1:
            if sep == "." and _is_number_dot(buffer, p):
                p = buffer.find(sep, p + 1)
                continue
            break
        if p != -1 and (earliest_pos == -1 or p < earliest_pos):
            earliest_pos, earliest_sep = p, sep
    return earliest_pos, earliest_sep


def extract_sentences(buffer: str) -> tuple:
    sentences = []
    seps = [".", "!", "?", "。", "！", "？", ",", "，", ":", "：", ";", "；"]
    min_len = config.min_sentence_len
    max_len = config.max_buffer_len

    while True:
        pos, _ = _find_sentence_end(buffer, seps)
        if pos == -1:
            break
        sentence = buffer[: pos + 1].strip()
        buffer = buffer[pos + 1:]
        if len(sentence) >= min_len:
            sentences.append(sentence)
        elif sentences:
            sentences[-1] += " " + sentence
        else:
            buffer = sentence + " " + buffer.lstrip()

    if len(buffer) > max_len:
        comma = buffer.rfind(",", 0, max_len)
        if comma > min_len:
            sentences.append(buffer[: comma + 1].strip())
            buffer = buffer[comma + 1:]
        else:
            space = buffer.rfind(" ", 0, max_len)
            if space > min_len:
                sentences.append(buffer[:space].strip())
                buffer = buffer[space + 1:]

    return sentences, buffer


class _AudioReorderer:
    """Gom audio theo index, gửi ra đúng thứ tự 1, 2, 3..."""

    def __init__(self, send_fn, log):
        self._send = send_fn
        self._log = log
        self._next_idx = 1
        self._buf: dict = {}
        self._lock = asyncio.Lock()
        self.total_ref = {"n": 0}

    async def push(self, idx: int, sentence: str, audio: bytes):
        async with self._lock:
            self._buf[idx] = (sentence, audio)
            while self._next_idx in self._buf:
                sent, data = self._buf.pop(self._next_idx)
                try:
                    await self._send({
                        "type": "audio",
                        "index": self._next_idx,
                        "total": self.total_ref["n"],
                        "sentence": sent,
                        "data": data,
                    })
                except Exception as e:
                    self._log.warning(f"⚠️ Reorderer #{self._next_idx}: {e}")
                self._next_idx += 1


class ConnectionHandler:
    def __init__(self, ws: WebSocket, session_id: int, device_id: str):
        self.ws = ws
        self.session_id = session_id
        self.device_id = device_id
        self.log = get_session_logger(session_id, device_id)

        self.dialogue = Dialogue()
        self._init_providers()

        self._captured = {
            "user_wav": None,
            "bot_mp3_parts": [],
        }
        self._pipeline_task: Optional[asyncio.Task] = None

    def _init_providers(self):
        self.asr = ProviderRegistry.create_asr(
            config.asr_provider,
            config={
                "url": config.asr_url,
                "model": config.asr_model,
                "language": config.asr_language,
                "request_timeout": config.asr_request_timeout,
            },
            log=self.log,
        )

        self.llm = ProviderRegistry.create_llm(
            config.llm_provider,
            config={
                "url": config.llm_url,
                "model": config.llm_model,
                "temperature": config.llm_temperature,
                "num_predict": config.llm_num_predict,
                "max_tool_iterations": config.llm_max_tool_iterations,
                "request_timeout": config.llm_request_timeout,
                "think": config.llm_think,        # ✅ Qwen 3.5
            },
            tools_schema=TOOLS_SCHEMA,
            log=self.log,
        )

        self.tts = ProviderRegistry.create_tts(
            config.tts_provider,
            config={
                "voice": config.tts_voice,
                "rate": config.tts_rate,
                "volume": config.tts_volume,
                "request_timeout": config.tts_request_timeout,
                "max_retries": config.tts_max_retries,
                "url": config.tts_vieneu_url,
                "edge_voice": config.tts_edge_voice,
                "piper_model": config.tts_piper_model,
                "piper_binary": config.tts_piper_binary,
            },
            log=self.log,
        )

        self.memory = ProviderRegistry.create_memory(
            config.memory_provider,
            config={
                "max_turns": config.memory_max_turns,
            },
            log=self.log,
        )

    def abort(self):
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            self.log.info("⏹️ Đã gửi cancel tới pipeline")

    async def handle_text(self, user_text: str) -> str:
        self.log.info(f"👤 User: {user_text}")

        normalized = user_text.strip().lower().rstrip(".!?,")

        # ═══ SHORTCUT: GREETING ═══
        GREETINGS = {
            "chào", "chào bạn", "hi", "hello", "xin chào",
            "chào đèn", "hey", "alo",
            "chào buổi sáng", "chào buổi chiều", "chào buổi tối",
        }
        if normalized in GREETINGS:
            return await self._quick_response(user_text, "Chào bạn!")

        # ═══ SHORTCUT: TIME / DATE ═══
        from datetime import datetime as _dt
        import re as _re
        _WD = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        _now = _dt.now()

        # Hỏi thứ
        if _re.search(r"(?i)(hôm\s*nay|nay).{0,10}thứ\s*mấy", normalized) \
                or normalized in {"thứ mấy", "hôm nay thứ", "hôm nay thứ mấy rồi"}:
            return await self._quick_response(
                user_text,
                f"Hôm nay là {_WD[_now.weekday()]}.",
            )

        # Hỏi ngày
        if _re.search(r"(?i)(hôm\s*nay|nay).{0,10}ngày\s*(bao\s*nhiêu|mấy)", normalized) \
                or normalized in {"ngày bao nhiêu", "hôm nay ngày mấy"}:
            return await self._quick_response(
                user_text,
                f"Hôm nay là ngày {_now.day} tháng {_now.month} năm {_now.year}.",
            )

        # Hỏi giờ
        if _re.search(r"(?i)(mấy\s*giờ|bây\s*giờ.{0,5}giờ)", normalized):
            return await self._quick_response(
                user_text,
                f"Bây giờ là {_now.hour} giờ {_now.minute} phút.",
            )

        # ═══ CÒN LẠI → LLM ═══
        self.dialogue.append_user(user_text)
        self._captured["bot_mp3_parts"] = []

        memory_ctx = await self.memory.get_context(str(self.session_id))
        messages = self.dialogue.to_llm_messages(
            memory_str=memory_ctx,
            system_prompt=config.system_prompt,
            max_turns=config.llm_history_keep,
        )

        self._pipeline_task = asyncio.create_task(self._stream_llm_tts(messages))
        try:
            full_response = await self._pipeline_task
        except asyncio.CancelledError:
            self.log.info("⏹️ Pipeline bị cancel")
            raise
        finally:
            self._pipeline_task = None

        # Lọc câu hỏi ngược
        full_response = _clean_response(full_response)
        self.dialogue.append_assistant(full_response)
        await self.memory.save(str(self.session_id), [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_response},
        ])
        return full_response

    async def handle_voice(self, audio_bytes: bytes) -> Optional[str]:
        try:
            wav = await any_to_wav(audio_bytes, sample_rate=config.sample_rate)
            self.log.info(f"🎵 Audio: {len(audio_bytes)} → WAV {len(wav)}b")
        except Exception as e:
            self.log.error(f"❌ Convert audio lỗi: {e}")
            await self._send_error(f"Lỗi audio: {e}")
            return None

        self._captured["user_wav"] = wav
        await self._send_callback({"type": "user_wav", "data": wav})
        await self._send_callback({"type": "status", "text": "Đang nghe..."})

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav)
        elapsed = (time.perf_counter() - t0) * 1000
        self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)

    async def _stream_llm_tts(self, messages: list) -> str:
        full_response = ""
        buffer = ""
        sentence_count = 0
        token_count = 0

        tts_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        stop_marker = object()
        num_workers = max(1, config.tts_workers)
        llm_timeout = max(10.0, float(config.llm_request_timeout))

        reorderer = _AudioReorderer(self._send_callback, self.log)

        await self._send_callback({"type": "tts_start"})

        async def tts_consumer(worker_id: int):
            while True:
                item = await tts_queue.get()
                if item is stop_marker:
                    break
                idx, sentence = item
                try:
                    t0 = time.perf_counter()
                    audio = await asyncio.wait_for(
                        self.tts.synthesize(sentence),
                        timeout=max(10.0, float(config.tts_request_timeout)),
                    )
                    elapsed = (time.perf_counter() - t0) * 1000
                    if audio:
                        await reorderer.push(idx, sentence, audio)
                        self.log.info(
                            f"🔊 W{worker_id} câu #{idx} "
                            f"({len(audio)}b, TTS={elapsed:.0f}ms)"
                        )
                except asyncio.TimeoutError:
                    self.log.warning(f"⏰ TTS câu #{idx} timeout")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"❌ TTS câu #{idx} lỗi: {e}")

        async def run_stream():
            nonlocal full_response, buffer, sentence_count, token_count
            async for item in self.llm.chat_stream(messages):
                t = item.get("type")
                if t == "tool":
                    self.log.info(f"🔧 Tool: {item.get('name')}")
                    await self._send_callback(
                        {"type": "tool", "name": item.get("name")}
                    )
                elif t == "token":
                    token_count += 1
                    tok = item.get("content", "")
                    full_response += tok
                    buffer += tok
                    await self._send_callback({"type": "token", "content": tok})

                    sents, buffer = extract_sentences(buffer)
                    for s in sents:
                        sentence_count += 1
                        reorderer.total_ref["n"] = sentence_count
                        self.log.info(f"[TTS_DBG] Extract #{sentence_count}: {s[:80]!r} (len={len(s)})")
                        await tts_queue.put((sentence_count, s))

            if buffer.strip():
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                self.log.info(f"[TTS_DBG] Câu cuối #{sentence_count}: {buffer[:80]!r} (len={len(buffer)})")
                await tts_queue.put((sentence_count, buffer.strip()))

        consumers = [
            asyncio.create_task(tts_consumer(i + 1))
            for i in range(num_workers)
        ]
        self.log.info(f"🔧 Khởi động {num_workers} TTS workers")

        try:
            await asyncio.wait_for(run_stream(), timeout=llm_timeout)
        except asyncio.TimeoutError:
            self.log.error(f"⏰ LLM stream timeout sau {llm_timeout}s")
            await self._send_callback({
                "type": "error",
                "text": "AI đang quá chậm hoặc không phản hồi. Vui lòng thử lại.",
            })
        except asyncio.CancelledError:
            self.log.info("⏹️ _stream_llm_tts bị cancel")
            raise
        except Exception as e:
            self.log.exception(f"❌ LLM stream lỗi: {e}")
        finally:
            for _ in range(num_workers):
                try:
                    tts_queue.put_nowait(stop_marker)
                except Exception:
                    pass
            try:
                await asyncio.gather(*consumers, return_exceptions=True)
            except asyncio.CancelledError:
                for c in consumers:
                    if not c.done():
                        c.cancel()
            try:
                await self._send_callback({"type": "tts_stop"})
            except Exception:
                pass

        self.log.info(f"✅ Xong: {token_count} tokens, {sentence_count} câu")
        return full_response

    async def _send_callback(self, payload: dict):
        try:
            ptype = payload["type"]
            if ptype == "audio":
                self._captured["bot_mp3_parts"].append(payload["data"])
                meta = {
                    "type": "audio_meta",
                    "index": payload.get("index", 0),
                    "size": len(payload["data"]),
                    "sentence": payload.get("sentence", ""),
                }
                await self.ws.send_json(meta)
                await self.ws.send_bytes(payload["data"])
            elif ptype == "user_wav":
                pass
            else:
                await self.ws.send_json(payload)
        except Exception as e:
            self.log.warning(f"⚠️ send_callback: {e}")

    async def _quick_response(self, user_text: str, response: str) -> str:
        """Trả lời nhanh không qua LLM nhưng CÓ TTS."""
        self.log.info(f"🤖 Quick response: {response!r}")

        self.dialogue.append_user(user_text)
        self.dialogue.append_assistant(response)
        self._captured["bot_mp3_parts"] = []

        try:
            await self._send_callback({"type": "token", "content": response})
        except Exception as e:
            self.log.warning(f"Quick token lỗi: {e}")

        try:
            audio = await asyncio.wait_for(
                self.tts.synthesize(response),
                timeout=10.0,
            )
            if audio:
                await self._send_callback({
                    "type": "audio",
                    "index": 1,
                    "total": 1,
                    "sentence": response,
                    "data": audio,
                })
                self.log.info(f"🔊 Quick TTS: {len(audio)}b")
            else:
                self.log.warning("Quick TTS trả rỗng")
        except asyncio.TimeoutError:
            self.log.warning("Quick TTS timeout 10s")
        except Exception as e:
            self.log.warning(f"Quick TTS lỗi: {e}")

        try:
            await self._send_callback({"type": "end"})
        except Exception:
            pass

        return response

    async def _send_error(self, message: str):
        await self._send_callback({"type": "error", "text": message})

    async def send_end(self):
        await self._send_callback({"type": "end"})

    def get_captured(self, key: str):
        if key == "bot_mp3":
            parts = self._captured.get("bot_mp3_parts") or []
            return b"".join(parts) if parts else None
        return self._captured.get(key)

    def load_history(self, history: list):
        """Load history từ DB vào dialogue."""
        for h in history[-config.llm_history_keep:]:
            self.dialogue.put(Message(role=h["role"], content=h["content"]))

    async def handle_voice_wav(self, wav_bytes: bytes) -> Optional[str]:
        self._captured["user_wav"] = wav_bytes
        await self._send_callback({"type": "user_wav", "data": wav_bytes})
        await self._send_callback({"type": "status", "text": "Đang nghe..."})

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)


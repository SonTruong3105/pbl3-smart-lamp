"""ConnectionHandler — xử lý vòng đời 1 WebSocket, TTS song song."""
import asyncio
import json
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
from app.core.providers.tools.registry import TOOLS_SCHEMA, tools_for_query
from app.core.utils.opus_codec import OpusCodec
from app.core.utils.audio import any_to_wav
from app.core.lamp_automation import set_ai_visual_state
from app.core.providers.tools.unified import (
    Action,
    ActionResponse,
    FunctionRegistry,
    UnifiedToolHandler,
)
from app.core.providers.intent import (
    FunctionCallIntentProvider,
    IntentLLMProvider,
    NoIntentProvider,
)
import app.core.providers.tools.plugins  # noqa: F401 — đăng ký tool
import app.core.providers.memory.mem_local_short  # noqa: F401


def _clean_response(text: str) -> str:
    if not text: return text
    if text.strip().lower().startswith(("mình chưa rõ", "mình không rõ", "mình chưa hiểu", "mình không hiểu")):
        m = re.search(r"[.!?]", text)
        if m: return text[:m.end()].strip()

    BAD_PATTERNS = [
        r"(?i)bạn\s+cần\s+(giúp|hỗ\s+trợ|gì|mình)",
        r"(?i)bạn\s+có\s+(muốn|cần)",
        r"(?i)bạn\s+có\s+muốn\s+biết",
        r"(?i)mình\s+có\s+thể\s+(giúp|hỏi|kiểm\s+tra)",
        r"(?i)cần\s+mình\s+(giải\s+thích|lấy|kiểm\s+tra)",
        r"(?i)hay\s+bạn\s+muốn",
        r"(?i)bạn\s+muốn\s+(mình|tìm\s+hiểu|biết)",
        r"(?i)thông\s+tin\s+gì\s+khác",
        r"(?i)bạn\s+cần\s+biết\s+thêm",
        r"(?i)bạn\s+có\s+thắc\s+mắc",
    ]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [s.strip() for s in sentences if s.strip() and not any(re.search(p, s.strip()) for p in BAD_PATTERNS)]
    
    result = " ".join(cleaned).strip()
    result = _soften_numbers(result)
    result = re.sub(r"[#*_`>]+", "", result)
    return re.sub(r"\s+", " ", result).strip() or text


def _soften_numbers(text: str) -> str:
    """Chuyển số liệu thành cách nói tự nhiên hơn."""
    text = re.sub(r"(\d+)\.\d+\s*độ\s*C", r"khoảng \1 độ", text)
    text = re.sub(r"(\d+)\.\d+\s*°C", r"khoảng \1 độ", text)
    text = re.sub(r",?\s*\d+\.?\d*\s*km/h", "", text)
    text = re.sub(r",?\s*\(cảm\s+giác[^)]*\)", "", text)
    return text


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
        _original_len = len(buffer)
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
            # ⭐ FIX: sentence ngắn + sentences rỗng → append vào buffer
            # NHƯNG phải đảm bảo buffer mới KHÔNG bắt đầu bằng cùng separator
            # (tránh infinite loop tìm lại cùng vị trí)
            if sentence:
                buffer = sentence + " " + buffer.lstrip()
            else:
                buffer = buffer.lstrip()
            # Safety: nếu buffer không giảm → break
            if len(buffer) >= _original_len:
                break

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
    """Gom audio theo index, gui ra dung thu tu 1, 2, 3...

    Viec gui (ESP32 pace real-time 60ms/frame) chay trong 1 sender task rieng
    de TTS cua cau sau duoc tong hop trong luc cau truoc dang phat.
    """

    def __init__(self, send_fn, log):
        self._send = send_fn
        self._log = log
        self._next_idx = 1
        self._buf: dict = {}
        self._out: asyncio.Queue = asyncio.Queue()
        self._sender = None
        self.total_ref = {"n": 0}

    def start(self):
        if self._sender is None:
            self._sender = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            item = await self._out.get()
            if item is None:
                break
            i, sent, data = item
            try:
                await self._send({
                    "type": "audio",
                    "index": i,
                    "total": self.total_ref["n"],
                    "sentence": sent,
                    "data": data,
                })
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log.warning(f"Reorderer #{i}: {e}")

    def _drain(self):
        while self._next_idx in self._buf:
            item = self._buf.pop(self._next_idx)
            if item is not None:
                sent, data = item
                self._out.put_nowait((self._next_idx, sent, data))
            self._next_idx += 1

    async def push(self, idx: int, sentence: str, audio: bytes):
        self._buf[idx] = (sentence, audio)
        self._drain()

    async def skip(self, idx: int):
        self._buf[idx] = None
        self._drain()

    async def close(self, wait: bool = True):
        task = self._sender
        if task is None:
            return
        self._sender = None
        if wait:
            self._out.put_nowait(None)
            try:
                await asyncio.wait_for(task, timeout=15.0)
            except asyncio.CancelledError:
                task.cancel()
                raise
            except asyncio.TimeoutError:
                self._log.error("Audio sender timeout sau 15s -> huy")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except Exception:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


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
        self._closed = False

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
                "think": config.llm_think,
                "num_ctx": config.llm_num_ctx,
                "num_batch": config.llm_num_batch,
                "keep_alive": config.llm_keep_alive,
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

        # ── Unified tool handler (sử dụng ToolManager) ──
        self.tool_handler = UnifiedToolHandler(log=self.log)
        self.tool_handler.set_display_callback(self._notify_tool_display)

        # ── Intent provider ──
        intent_mode = config.intent_provider
        if intent_mode == "intent_llm":
            self.intent_provider = IntentLLMProvider(log=self.log)
        elif intent_mode == "nointent":
            self.intent_provider = NoIntentProvider()
        else:
            self.intent_provider = FunctionCallIntentProvider()


    async def _notify_tool_display(self, tool_name: str):
        """Gửi thông báo tool đang được gọi xuống client (nếu có)."""
        try:
            await self._send_callback({"type": "tool", "name": tool_name})
        except Exception:
            pass

    def abort(self):
        self._closed = True
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            self.log.info("⏹️ Đã gửi cancel tới pipeline")
        try:
            self._captured["bot_mp3_parts"] = []
        except Exception:
            pass


    def _build_tool_schema(self, query: str) -> list:
        from app.core.providers.tools.registry import tool_names_for_query, DIRECT_ANSWER_TOOL
        from app.core.providers.tools.unified.register import all_function_registry
        names = tool_names_for_query(query)
        if names:
            return [
                {"type": "function", "function": {
                    "name": v.name, "description": v.description, "parameters": v.parameters,
                }}
                for k, v in all_function_registry.items() if k in names
            ] + [DIRECT_ANSWER_TOOL]
        return [DIRECT_ANSWER_TOOL]


    async def handle_text(self, user_text: str) -> str:
        self.log.info(f"👤 User: {user_text}")

        # ═══ FAST TRACK (nếu có) ═══
        try:
            from app.core.routing.fast_track import process_fast_track
            fast = await process_fast_track(
                user_text, self._quick_response, self.log,
            )
            if fast is not None:
                return fast
        except Exception as e:
            self.log.debug(f"fast_track lỗi (bỏ qua): {e}")

        # ═══ CÒN LẠI → LLM ═══

        self.dialogue.append_user(user_text)
        self._captured["bot_mp3_parts"] = []

        memory_ctx = await self.memory.get_context(str(self.session_id))
        messages = self.dialogue.to_llm_messages(
            memory_str=memory_ctx,
            system_prompt=config.system_prompt,
            max_turns=config.llm_history_keep,
        )

        tools = self._build_tool_schema(user_text)
        self.log.info(f"Tools: {[t['function']['name'] for t in tools]}")
        await set_ai_visual_state("thinking", self.log)
        self._pipeline_task = asyncio.create_task(
            self._stream_llm_tts(messages, tools=tools)
        )
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


    async def chat_with_tools(self, messages: list, tools: list) -> str:
        # Intent provider (intent_llm / nointent)
        if self.intent_provider:
            last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            intent_tool = await self.intent_provider.detect_intent(self, last_user)
            if intent_tool:
                self.log.info(f"IntentLLM chọn tool: {intent_tool}")
                action = await self.tool_handler.execute(self, intent_tool, {})
                if action.action == Action.RESPONSE:
                    await self._send_callback({"type": "token", "content": action.response})
                    return action.response
                # REQLLM: chèn kết quả vào messages rồi tiếp tục
                messages = list(messages) + [
                    {"role": "tool", "tool_name": intent_tool, "content": action.result}
                ]

        """
        Vòng lặp chat có tool calling — tương đương ConnectionHandler.chat()
        của server gốc.

        - Gọi LLM với tools.
        - Nếu có tool_call: thực thi qua UnifiedToolHandler.
        - Nếu Action.REQLLM: chèn kết quả vào dialogue, gọi lại LLM.
        - Nếu Action.RESPONSE: trả về trực tiếp.
        - Nếu Action.RECORD: ghi nhận, không gọi lại LLM.
        - Lặp tối đa config.llm_max_tool_iterations lần.
        """
        max_iter = max(1, config.llm_max_tool_iterations)
        current_messages = list(messages)
        full_response = ""

        for iteration in range(max_iter):
            tool_calls: list[dict] = []
            token_buffer = ""

            async for event in self.llm.response_with_functions(
                current_messages, tools=tools
            ):
                if event["type"] == "token":
                    token = event["content"]
                    token_buffer += token
                    full_response += token
                    # Đẩy token vào TTS pipeline
                    await self._send_callback(
                        {"type": "token", "content": token}
                    )
                elif event["type"] == "tool_call":
                    tool_calls.append(event)

            if not tool_calls:
                return full_response

            # Ghi assistant message có tool_calls
            current_messages.append({
                "role": "assistant",
                "content": token_buffer or "",
                # Ollama format: chỉ function.{name, arguments(dict)}
                "tool_calls": [
                    {
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Thực thi từng tool
            need_reqllm = False
            for tc in tool_calls:
                name = tc["name"]
                args = tc["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                self.log.info(f"🔧 Tool call: {name}({args})")
                action_resp = await self.tool_handler.execute(self, name, args)

                # Ghi tool message (Ollama dùng tool_name, KHÔNG phải tool_call_id)
                current_messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": action_resp.result or "",
                })

                if action_resp.action == Action.RESPONSE:
                    # Trả lời trực tiếp, không qua LLM
                    if action_resp.response:
                        await self._send_callback({
                            "type": "token",
                            "content": action_resp.response,
                        })
                    return action_resp.response or full_response

                if action_resp.action == Action.REQLLM:
                    need_reqllm = True

                if action_resp.action in (Action.NOTFOUND, Action.ERROR):
                    # Tool không tồn tại hoặc lỗi → yêu cầu LLM sửa lại
                    need_reqllm = True

                if action_resp.action == Action.RECORD:
                    # Ghi nhận nhưng không gọi lại LLM
                    if action_resp.response:
                        await self._send_callback({
                            "type": "token",
                            "content": action_resp.response,
                        })

            if not need_reqllm:
                return full_response

        self.log.warning(f"⚠️ Vượt quá {max_iter} vòng tool calling")
        return full_response

    async def _stream_llm_tts(self, messages: list, tools=None) -> str:
        """Pipeline LLM → TTS với tool calling, dùng chat_with_tools()."""
        full_response = ""
        sentence_count = 0
        token_count = 0

        tts_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        stop_marker = object()
        num_workers = max(1, config.tts_workers)
        llm_timeout = max(10.0, float(config.llm_request_timeout))

        reorderer = _AudioReorderer(self._send_callback, self.log)
        reorderer.start()

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
                            f"W{worker_id} cau #{idx} "
                            f"({len(audio)}b, TTS={elapsed:.0f}ms)"
                        )
                    else:
                        await reorderer.skip(idx)
                except asyncio.TimeoutError:
                    await reorderer.skip(idx)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await reorderer.skip(idx)

        # Thu thập token và tách câu để đẩy vào TTS queue
        buffer = ""

        async def on_token(tok: str):
            nonlocal sentence_count, buffer, token_count
            token_count += 1
            buffer += tok
            sents, buffer = extract_sentences(buffer)
            for s in sents:
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    await asyncio.wait_for(
                        tts_queue.put((sentence_count, s)), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    await reorderer.skip(sentence_count)

        # Gọi chat_with_tools và hook token callback
        original_send = self._send_callback

        async def hooked_send(payload: dict):
            if payload.get("type") == "token":
                await on_token(payload.get("content", ""))
            await original_send(payload)

        self._send_callback = hooked_send

        cancelled = False
        consumers = [
            asyncio.create_task(tts_consumer(i + 1))
            for i in range(num_workers)
        ]

        try:
            full_response = await asyncio.wait_for(
                self.chat_with_tools(messages, tools or []),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            self.log.error(f"⏰ LLM timeout sau {llm_timeout}s")
            await original_send({
                "type": "error",
                "text": "AI đang quá chậm hoặc không phản hồi.",
            })
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as e:
            self.log.exception(f"❌ LLM stream lỗi: {e}")
        finally:
            self._send_callback = original_send

            remainder = buffer.strip()
            if remainder and len(remainder) >= config.min_sentence_len:
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    await asyncio.wait_for(
                        tts_queue.put((sentence_count, remainder)),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    pass
            elif remainder and sentence_count == 0:
                # Chưa có câu nào → vẫn phải TTS
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    await asyncio.wait_for(
                        tts_queue.put((sentence_count, remainder)),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    pass
            elif remainder:
                self.log.debug(
                    f"⏭️ Bỏ qua buffer ngắn: {remainder!r} "
                    f"(len={len(remainder)} < {config.min_sentence_len})"
                )

            if cancelled:
                for c in consumers:
                    if not c.done():
                        c.cancel()
                await asyncio.gather(*consumers, return_exceptions=True)
                await reorderer.close(wait=False)
            else:
                for _ in range(num_workers):
                    try:
                        await asyncio.wait_for(
                            tts_queue.put(stop_marker), timeout=5.0
                        )
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*consumers, return_exceptions=True),
                        timeout=max(10.0, float(config.tts_request_timeout) + 5.0),
                    )
                except asyncio.TimeoutError:
                    for c in consumers:
                        if not c.done():
                            c.cancel()
                    await asyncio.gather(*consumers, return_exceptions=True)
                await reorderer.close(wait=True)

            try:
                await original_send({"type": "tts_stop"})
            except Exception:
                pass

        self.log.info(f"✅ Xong: {token_count} tokens, {sentence_count} câu")
        await set_ai_visual_state("idle", self.log)
        return full_response


    async def _send_callback(self, payload: dict):
        if self._closed:
            return
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
                await asyncio.wait_for(self.ws.send_json(meta), timeout=10.0)
                await asyncio.wait_for(
                    self.ws.send_bytes(payload["data"]),
                    timeout=10.0,
                )
            elif ptype == "user_wav":
                pass
            else:
                await asyncio.wait_for(self.ws.send_json(payload), timeout=10.0)
        except asyncio.TimeoutError:
            self._closed = True
            self.log.error("WebSocket send timeout sau 10s")
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

        # Giới hạn độ dài TTS — voice friendly, cắt sớm để tránh audio dài
        # Lưu ý: clean_for_tts có thể expand text ~1.3x (23.5 → 23 phẩy 5)
        # nên cắt 100 chars trước clean → sau clean ~130 chars
        tts_text = response[:100].rsplit(" ", 1)[0] if len(response) > 100 else response
        # Đảm bảo kết thúc bằng dấu câu (tránh cắt giữa từ)
        if len(response) > 100 and not tts_text.rstrip().endswith((".", "!", "?")):
            tts_text = tts_text.rstrip(",;:") + "."
        try:
            audio = await asyncio.wait_for(
                self.tts.synthesize(tts_text),
                timeout=15.0,
            )
            if audio:
                # Circuit breaker: nếu audio > 400KB (≈10s), cắt bớt
                if len(audio) > 400_000:
                    self.log.warning(
                        f"⚠️ Audio quá lớn ({len(audio)}b) — cắt bớt"
                    )
                    audio = audio[:400_000]
                await self._send_callback({
                    "type": "audio",
                    "index": 1,
                    "total": 1,
                    "sentence": tts_text,
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
        await set_ai_visual_state("listening", self.log)

        t0 = time.perf_counter()
        user_text = await self.asr.transcribe(wav_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        self.log.info(f"📝 ASR [{elapsed:.0f}ms]: '{user_text}'")

        if not user_text:
            await self._send_error("Không nhận dạng được")
            return None

        await self._send_callback({"type": "stt", "text": user_text})
        return await self.handle_text(user_text)

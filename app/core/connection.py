"""ConnectionHandler — xử lý vòng đời 1 WebSocket, TTS song song."""
import asyncio
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
import json
import time
from typing import Awaitable, Callable, Optional

from fastapi import WebSocket

from app.config import config
from app.core.automation import set_ai_visual_state
from app.core.logger import get_session_logger
from app.core.providers.asr import phowhisper  # noqa
from app.core.providers.base import ProviderRegistry
from app.core.providers.intent import (
    FunctionCallIntentProvider,
    IntentLLMProvider,
    NoIntentProvider,
)
from app.core.providers.llm import ollama  # noqa
from app.core.providers.memory import local, none  # noqa
import app.core.providers.memory.mem_local_short  # noqa: F401
import app.core.providers.tools.plugins  # noqa: F401 — đăng ký tool
from app.core.providers.tools.registry import TOOLS_SCHEMA
from app.core.providers.tools.unified import (
    Action,
    ActionResponse,
    UnifiedToolHandler,
)
from app.core.providers.tts import edge, piper, vieneu  # noqa
from app.core.routing.fast_track import (
    NEGATED_DEVICE_RE,
    WEEKDAYS_VI as _WEEKDAYS_VI,
    process_fast_track,
)
from app.core.routing.intent_filter import (
    build_tool_schema,
    is_music_request,
    looks_like_pure_chat,
)
from app.core.routing.fast_track import (
    FAREWELL_RE as _FAREWELL_RE,
    _norm,
)
from app.core.utils.audio import any_to_wav
from app.core.utils.audio_reorderer import _AudioReorderer
from app.core.utils.dialogue import Dialogue, Message
from app.core.utils.sentence_splitter import extract_sentences
from app.core.utils.text_cleaner import (
    clean_response as _clean_response,
    compact_tool_result as _compact_tool_result,
    filter_chinese as _filter_chinese,
)
from app.core.utils.tts_cache import get_cache
from app.music import MusicError, ogg_to_browser_mp3

_VN_TZ = _tz(_td(hours=7))


class ConnectionHandler:
    def __init__(self, ws: WebSocket, session_id: int, device_id: str):
        self.ws = ws
        self.session_id = session_id
        self.device_id = device_id
        self.log = get_session_logger(session_id, device_id)

        self.dialogue = Dialogue()
        self._init_providers()

        self._pipeline_task: Optional[asyncio.Task] = None
        self._background_tasks: set[asyncio.Task] = set()
        self._quick_tts_task: Optional[asyncio.Task] = None
        self._closed = False

        self._pending_calendar = None
        self._reset_turn_state()
        self._music_playing = False

    def _reset_turn_state(self, keep_user_wav: bool = False):
        user_wav = self._captured.get("user_wav") if keep_user_wav else None
        self._captured = {
            "user_wav": user_wav,
            "bot_mp3_parts": [],
        }
        self._pending_music = None
        self._end_sent = False
        self._close_after_end = False

    @property
    def transport(self):
        """Alias tương thích — transport được lưu ở ``self.ws``.

        Các call site trong routes/chat_ws.py dùng ``handler.transport`` để gửi
        lệnh MCP xuống ESP32; trước đây thuộc tính này bị thiếu.
        """
        return self.ws

    async def _stop_audio(self):
        # Base no-op. ESP32ConnectionHandler override.
        pass

    async def notify_reminder(self, reminder: dict) -> None:
        if self._music_playing:
            self._music_playing = False
            try:
                await self._stop_audio()
            except Exception as e:
                self.log.debug(f"Dừng nhạc khi nhắc hẹn lỗi: {e}")

        text = reminder["text"]
        audio = await self.tts.synthesize(text)
        if not audio:
            raise RuntimeError("TTS empty")
        await self._send_callback({
            "type": "audio",
            "index": 1,
            "total": 1,
            "sentence": text,
            "reminder_id": reminder.get("reminder_id", reminder.get("id")),
            "data": audio,
        })
        await self._send_callback({"type": "tts_stop"})

    def _init_providers(self):
        from app.core.runtime import get_runtime
        runtime = get_runtime()

        if runtime is not None:
            self.asr = runtime.asr
            self.llm = runtime.llm
            self.tts = runtime.tts
            self.tool_handler = runtime.tool_handler
        else:
            self._init_local_providers()
            self.tool_handler = UnifiedToolHandler(log=self.log)

        self.tool_handler.set_display_callback(self._notify_tool_display)

        self.memory = ProviderRegistry.create_memory(
            config.memory_provider,
            config={"max_turns": config.memory_max_turns},
            log=self.log,
        )

        intent_mode = config.intent_provider
        if intent_mode == "intent_llm":
            self.intent_provider = IntentLLMProvider(log=self.log)
        elif intent_mode == "nointent":
            self.intent_provider = NoIntentProvider()
        else:
            self.intent_provider = FunctionCallIntentProvider()

    def _init_local_providers(self):
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

    async def _notify_tool_display(self, tool_name: str):
        """Gửi thông báo tool đang được gọi xuống client."""
        try:
            await self._send_callback({"type": "tool", "name": tool_name})
        except Exception as e:
            self.log.debug(f"Notify tool display lỗi: {e}")

    async def abort(self):
        self._closed = True
        for task in tuple(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        task = self._pipeline_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._pipeline_task = None
        self._captured["bot_mp3_parts"] = []

    async def _emit_token(
        self,
        text: str,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """Gửi token text xuống client và kích hoạt hook tách câu TTS nếu có."""
        if not text:
            return
        if on_token is not None:
            await on_token(text)
        await self._send_callback({"type": "token", "content": text})

    async def handle_text(self, user_text: str) -> str:
        self.log.info(f"👤 User: {user_text}")
        self._end_sent = False
        self._close_after_end = False
        self._pending_music = None

        if _FAREWELL_RE.fullmatch(_norm(user_text)):
            self._close_after_end = True
            reply = "Tạm biệt bạn nhé. Mình dừng lắng nghe đây, cần gì cứ gọi mình nha."
            return await self._quick_response(user_text, reply)

        pending_calendar = self._pending_calendar
        if pending_calendar:
            normalized = " ".join(user_text.strip().lower().split()).strip(".!? ")
            if normalized in {"xác nhận", "đồng ý", "đồng ý nhé", "có", "ừ", "vâng", "ok", "okay"}:
                from app.core.providers.tools.calendar import execute_pending
                response = await execute_pending(self, pending_calendar.get("token"))
                return await self._quick_response(user_text, response)
            if normalized in {"hủy", "huỷ", "không", "thôi", "bỏ qua", "không cần"}:
                self._pending_calendar = None
                return await self._quick_response(user_text, "Ừ, mình hủy đề xuất lịch này nhé.")
            self._pending_calendar = None

        # 1. FAST TRACK
        injected_context = None
        try:
            fast = await process_fast_track(
                user_text,
                self._quick_response,
                self.log,
                execute_tool=lambda name, args: self.tool_handler.execute(self, name, args),
            )
            if isinstance(fast, dict) and "__llm_context__" in fast:
                injected_context = fast["__llm_context__"]
            elif fast is not None:
                return fast
        except Exception as e:
            self.log.debug(f"fast_track lỗi (bỏ qua): {e}")

        # 2. LLM + TTS PIPELINE
        self.dialogue.append_user(user_text)
        self._captured["bot_mp3_parts"] = []

        now = _dt.now(_VN_TZ)
        weekday_vi = _WEEKDAYS_VI[now.weekday()]
        sys_prompt = (
            f"{config.system_prompt}\n"
            f"[Thời gian hiện tại (UTC+7): {now.strftime('%H:%M')} {weekday_vi}, ngày {now.strftime('%Y-%m-%d')}]\n"
            "Nhịp điệu hội thoại: Nói tự nhiên, nhẹ nhàng, thân thiện như người bạn; thường 1-2 câu ngắn, "
            "không rập khuôn đầu câu. Khi người dùng chia sẻ cảm xúc, đồng cảm ngắn gọn trước khi gợi ý tiếp; "
            "chỉ gọi tool khi có ý định rõ ràng và không suy đoán khi thiếu ngữ cảnh."
        )
        if injected_context:
            sys_prompt += (
                f"\n\n[DỮ LIỆU LỊCH HỆ THỐNG]:\n{injected_context}\n"
                "Trả lời trực tiếp bằng 1-2 câu tiếng Việt tự nhiên, dễ nghe qua loa; không gọi thêm tool."
            )

        messages = self.dialogue.to_llm_messages(
            memory_str=None,
            system_prompt=sys_prompt,
            max_turns=config.llm_history_keep * 2,
        )

        tools = [] if injected_context else build_tool_schema(user_text, log=self.log)
        await set_ai_visual_state("thinking", self.log)
        self._pipeline_task = asyncio.create_task(
            self._stream_llm_tts(messages, tools=tools, skip_intent=bool(injected_context))
        )
        try:
            full_response = await self._pipeline_task
        except asyncio.CancelledError:
            self.log.info("⏹️ Pipeline bị cancel")
            raise
        finally:
            self._pipeline_task = None

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
        return await self.handle_voice_wav(wav)

    async def handle_voice_wav(self, wav_bytes: bytes) -> Optional[str]:
        self._reset_turn_state(keep_user_wav=False)
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

    async def chat_with_tools(
        self,
        messages: list,
        tools: list,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        skip_intent: bool = False,
    ) -> str:
        """Tool loop: Intent router (Qwen 0.8B) + Native tool calling."""
        max_iter = max(1, int(config.llm_max_tool_iterations))
        current_messages = list(messages)

        domain = "chat"
        intent_result = None
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        music_req = is_music_request(last_user)

        if not skip_intent and isinstance(self.intent_provider, IntentLLMProvider):
            if music_req:
                self.log.info(f"⏩ Skip intent (music request): {last_user[:40]!r}")
            elif looks_like_pure_chat(last_user):
                self.log.info(f"⏩ Skip intent (pure chat): {last_user[:40]!r}")
            else:
                try:
                    intent_result = await self.intent_provider.detect_intent_full(self, last_user)
                    if intent_result and intent_result.intent:
                        domain = intent_result.intent
                except Exception as e:
                    self.log.warning(f"⚠️ Intent lỗi (fallback chat): {e}")

        self.log.info(f"🎯 Intent Domain: {domain}")

        if not skip_intent and intent_result and intent_result.tool and not intent_result.needs_args:
            self.log.info(f"⚡ Fastpath: {intent_result.tool} (no args)")
            try:
                action_resp = await self.tool_handler.execute(self, intent_result.tool, {})
                if action_resp.action in (Action.RESPONSE, Action.RECORD):
                    final_text = _clean_response(str(action_resp.response or action_resp.result).strip())
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
                if action_resp.action == Action.ERROR:
                    final_text = "Mình không thực hiện được yêu cầu lúc này."
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text
            except Exception as e:
                self.log.warning(f"⚡ Fastpath lỗi: {e} — fallback LLM")

        if not skip_intent and isinstance(self.intent_provider, IntentLLMProvider):
            if domain != "chat":
                tools = build_tool_schema(last_user, domain=domain, log=self.log) or tools
            elif not music_req:
                tools = [t for t in tools if t.get("function", {}).get("name") == "direct_answer"]

        for iteration in range(max_iter):
            token_parts = []
            tool_calls = []
            prebuffer = ""
            prebuffered = 0
            flushed = False
            PREFETCH_TOKENS = 15

            async for event in self.llm.response_with_functions(current_messages, tools=tools):
                etype = event.get("type")
                if etype == "token":
                    tok = event.get("content", "")
                    if not tok:
                        continue
                    token_parts.append(tok)
                    if not tool_calls:
                        if not flushed:
                            prebuffer += tok
                            prebuffered += 1
                            if prebuffered >= PREFETCH_TOKENS:
                                flushed = True
                                await self._emit_token(prebuffer, on_token=on_token)
                                prebuffer = ""
                        else:
                            await self._emit_token(tok, on_token=on_token)
                elif etype == "tool_call":
                    tool_calls.append(event)
                    prebuffer = ""

            if not tool_calls:
                if not flushed and prebuffer:
                    await self._emit_token(prebuffer, on_token=on_token)
                return _clean_response("".join(token_parts).strip())

            assistant_calls = []
            normalized_calls = []
            for index, tc in enumerate(tool_calls):
                call_id = tc.get("id") or f"xiaozhi_{iteration}_{index}"
                name = tc.get("name") or ""
                raw_args = tc.get("arguments", {})
                parsed_args = raw_args
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args or "{}")
                    except Exception:
                        parsed_args = {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}

                normalized_calls.append((call_id, name, parsed_args))
                assistant_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": raw_args if isinstance(raw_args, str) else parsed_args,
                    },
                })

            current_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": assistant_calls,
            })

            should_continue = False
            for call_id, name, args in normalized_calls:
                if not name:
                    result_text = "Tool call không có tên hợp lệ."
                    action_kind = Action.ERROR
                    action_response = None
                else:
                    self.log.info(f"Tool call [{call_id}]: {name}({args})")
                    if name == "control_light" and NEGATED_DEVICE_RE.search(last_user):
                        refusal = "Được, mình sẽ không thực hiện lệnh điều khiển đèn đó."
                        action_resp = ActionResponse(
                            Action.RESPONSE, result=refusal, response=refusal,
                        )
                    else:
                        action_resp = await self.tool_handler.execute(self, name, args)
                    result_text = str(action_resp.result or action_resp.response or "")
                    action_kind = action_resp.action
                    action_response = action_resp.response

                current_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _compact_tool_result(result_text, max_chars=400),
                })

                if action_kind in (Action.RESPONSE, Action.RECORD):
                    final_text = _clean_response(str(action_response or result_text).strip())
                    await self._emit_token(final_text, on_token=on_token)
                    return final_text

                if action_kind in (Action.REQLLM, Action.NOTFOUND, Action.ERROR):
                    should_continue = True

            if not should_continue:
                return ""

        self.log.warning(f"Vượt quá {max_iter} vòng tool calling")
        return "Mình chưa thể hoàn tất yêu cầu vì đã vượt quá số lần gọi công cụ cho phép."

    async def _stream_llm_tts(self, messages: list, tools=None, skip_intent: bool = False) -> str:
        """Pipeline LLM -> TTS song song kèm Audio Reorderer."""
        full_response = ""
        sentence_count = 0
        token_count = 0
        buffer = ""

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
                        self.log.info(f"W{worker_id} cau #{idx} ({len(audio)}b, TTS={elapsed:.0f}ms)")
                    else:
                        await reorderer.skip(idx)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await reorderer.skip(idx)

        async def on_token(tok: str):
            nonlocal sentence_count, buffer, token_count
            token_count += 1
            buffer += tok
            sents, buffer = extract_sentences(buffer)
            for s in sents:
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    tts_queue.put_nowait((sentence_count, s))
                except asyncio.QueueFull:
                    await reorderer.skip(sentence_count)

        cancelled = False
        consumers = [asyncio.create_task(tts_consumer(i + 1)) for i in range(num_workers)]

        try:
            full_response = await asyncio.wait_for(
                self.chat_with_tools(messages, tools or [], on_token=on_token, skip_intent=skip_intent),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            self.log.error(f"⏰ LLM timeout sau {llm_timeout}s")
            await self._send_error("AI đang quá chậm hoặc không phản hồi.")
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as e:
            self.log.exception(f"❌ LLM stream lỗi: {e}")
        finally:
            remainder = buffer.strip()
            if remainder and (len(remainder) >= config.min_sentence_len or sentence_count == 0):
                sentence_count += 1
                reorderer.total_ref["n"] = sentence_count
                try:
                    tts_queue.put_nowait((sentence_count, remainder))
                except asyncio.QueueFull:
                    await reorderer.skip(sentence_count)

            if cancelled:
                for c in consumers:
                    if not c.done():
                        c.cancel()
                await asyncio.gather(*consumers, return_exceptions=True)
                await reorderer.close(wait=False)
            else:
                for _ in range(num_workers):
                    try:
                        await asyncio.wait_for(tts_queue.put(stop_marker), timeout=5.0)
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
                await self._send_callback({"type": "tts_stop"})
            except Exception as e:
                self.log.debug(f"Gửi tts_stop lỗi: {e}")

            await self.flush_pending_music()

        self.log.info(f"✅ Xong: {token_count} tokens, {sentence_count} câu")
        await set_ai_visual_state("idle", self.log)
        return full_response

    async def _send_callback(self, payload: dict):
        if self._closed:
            return
        try:
            ptype = payload.get("type")
            if ptype == "token":
                content = payload.get("content")
                if content and isinstance(content, str):
                    filtered = _filter_chinese(content)
                    if filtered != content:
                        payload = dict(payload, content=filtered)

            if ptype == "audio":
                self._captured["bot_mp3_parts"].append(payload["data"])
                meta = {
                    "type": "audio_meta",
                    "index": payload.get("index", 0),
                    "size": len(payload["data"]),
                    "sentence": payload.get("sentence", ""),
                    **({"reminder_id": payload["reminder_id"]} if payload.get("reminder_id") else {}),
                }
                await asyncio.wait_for(self.ws.send_json(meta), timeout=10.0)
                await asyncio.wait_for(self.ws.send_bytes(payload["data"]), timeout=10.0)
            elif ptype == "music":
                audio = payload.get("data") or b""
                if not audio:
                    return
                try:
                    audio = await ogg_to_browser_mp3(audio)
                except MusicError as exc:
                    self.log.error(f"🎵 Không chuyển được nhạc cho trình duyệt: {exc}")
                    await asyncio.wait_for(self.ws.send_json({
                        "type": "music_status",
                        "stage": "error",
                        "label": payload.get("label", ""),
                    }), timeout=10.0)
                    return
                await asyncio.wait_for(self.ws.send_json({
                    "type": "music_meta",
                    "size": len(audio),
                    "label": payload.get("label", ""),
                    "mime": "audio/mpeg",
                }), timeout=10.0)
                await asyncio.wait_for(self.ws.send_bytes(audio), timeout=30.0)
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
        """Trả lời text ngay, còn TTS chạy nền và được quản lý theo turn."""
        self.log.info(f"🤖 Quick response: {response!r}")

        self.dialogue.append_user(user_text)
        self.dialogue.append_assistant(response)
        self._captured["bot_mp3_parts"] = []

        try:
            await self._send_callback({"type": "token", "content": response})
        except Exception as e:
            self.log.warning(f"Quick token lỗi: {e}")

        max_quick_chars = max(120, int(getattr(config, "quick_tts_max_chars", 220)))
        tts_text = response[:max_quick_chars].rsplit(" ", 1)[0] if len(response) > max_quick_chars else response
        if len(response) > max_quick_chars and not tts_text.rstrip().endswith((".", "!", "?")):
            tts_text = tts_text.rstrip(",;:") + "."

        if self._quick_tts_task and not self._quick_tts_task.done():
            self._quick_tts_task.cancel()
            await asyncio.gather(self._quick_tts_task, return_exceptions=True)

        async def synthesize_quick_audio():
            cache = get_cache()
            audio = cache.get(tts_text, config.tts_voice)
            if audio is None:
                audio = await asyncio.wait_for(self.tts.synthesize(tts_text), timeout=15.0)
                if audio:
                    cache.put(tts_text, audio, config.tts_voice)
            if audio:
                CHUNK_SIZE = 400_000
                total = (len(audio) + CHUNK_SIZE - 1) // CHUNK_SIZE
                if total > 1:
                    self.log.warning(f"⚠️ Audio {len(audio)}b → {total} chunks")
                for i, start in enumerate(range(0, len(audio), CHUNK_SIZE), 1):
                    chunk = audio[start:start + CHUNK_SIZE]
                    await self._send_callback({
                        "type": "audio",
                        "index": i,
                        "total": total,
                        "sentence": tts_text if i == 1 else "",
                        "data": chunk,
                    })
                await self._send_callback({"type": "tts_stop"})
                self.log.info(f"🔊 Quick TTS: {len(audio)}b")
            else:
                self.log.warning("Quick TTS trả rỗng")

        self._quick_tts_task = asyncio.create_task(synthesize_quick_audio())
        self._background_tasks.add(self._quick_tts_task)
        self._quick_tts_task.add_done_callback(self._background_tasks.discard)
        return response

    async def wait_for_quick_audio(self):
        task = self._quick_tts_task
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.log.warning(f"Quick TTS lỗi: {e}")

    async def flush_pending_music(self):
        pending_music = self._pending_music
        self._pending_music = None
        if not pending_music or not pending_music.get("audio"):
            return
        audio = pending_music["audio"]
        self.log.info(f"🎵 Gửi music xuống client: {pending_music.get('label', '')!r} {len(audio)}b")
        await self._send_callback({
            "type": "music",
            "label": pending_music.get("label", ""),
            "mime": "audio/ogg",
            "data": audio,
        })

    async def _send_error(self, message: str):
        await self._send_callback({"type": "error", "text": message})

    async def send_end(self):
        if self._end_sent:
            return
        self._end_sent = True

        await self._send_callback({"type": "end"})
        if self._close_after_end and hasattr(self.ws, "send_audio"):
            self._close_after_end = False
            # Closing the ESP32 audio socket returns firmware to wake-word idle.
            await self.ws.close()
            return
        await asyncio.sleep(0.5)
        if self._close_after_end:
            self._close_after_end = False
            await self._send_callback({"type": "listen", "state": "stop"})
            return

        await self._send_callback({
            "type": "listen",
            "state": "start",
            "mode": "auto",
        })

    def get_captured(self, key: str):
        if key == "bot_mp3":
            parts = self._captured.get("bot_mp3_parts") or []
            return b"".join(parts) if parts else None
        return self._captured.get(key)

    def load_history(self, history: list):
        """Load history từ DB vào dialogue."""
        for h in history:
            self.dialogue.put(Message(role=h["role"], content=h["content"]))

    async def ack_reminder(self, reminder_id: str) -> None:
        try:
            from app.core.reminder_engine import get_engine
            await get_engine().ack(reminder_id)
        except Exception as e:
            self.log.warning(f"ack_reminder failed: {e}")
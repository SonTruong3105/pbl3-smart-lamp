"""Ollama LLM provider — stream thật, hỗ trợ Qwen 3.5 thinking."""
import json
import httpx
from typing import AsyncGenerator
from app.core.providers.base import LLMProviderBase, ProviderRegistry


class OllamaProvider(LLMProviderBase):
    async def chat_stream(self, messages, tools=None) -> AsyncGenerator[dict, None]:
        url = self.config.get("url")
        model = self.config.get("model")
        timeout = self.config.get("request_timeout", 120.0)
        max_iter = self.config.get("max_tool_iterations", 5)
        temperature = self.config.get("temperature", 0.7)
        num_predict = self.config.get("num_predict", 512)
        num_ctx = self.config.get("num_ctx")
        num_batch = self.config.get("num_batch")
        keep_alive = self.config.get("keep_alive")
        # ✅ Qwen 3.5 thinking mode — mặc định tắt
        think = self.config.get("think", False)

        tools_to_use = tools if tools is not None else self.tools_schema

        for iteration in range(max_iter):
            options = {
                "temperature": temperature,
                "num_predict": num_predict,
            }
            if num_ctx is not None:
                options["num_ctx"] = num_ctx
            if num_batch is not None:
                options["num_batch"] = num_batch

            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "think": think,
                "options": options,
            }
            if keep_alive is not None:
                payload["keep_alive"] = keep_alive
            # Chỉ gửi tools khi có
            if tools_to_use:
                payload["tools"] = tools_to_use

            content_buffer = ""
            tool_calls_buffer = []

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, json=payload) as r:
                        r.raise_for_status()
                        async for line in r.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            msg = chunk.get("message", {})

                            # ✅ Bỏ qua thinking content (Qwen 3.5)
                            tok = msg.get("content")
                            if tok:
                                content_buffer += tok
                                yield {"type": "token", "content": tok}

                            # ✅ Nếu có thinking field riêng, cũng bỏ qua
                            # (không đưa vào buffer để không TTS thinking)

                            for tc in (msg.get("tool_calls") or []):
                                tool_calls_buffer.append(tc)

                            if chunk.get("done"):
                                break

            except httpx.ConnectError:
                self.log.error("❌ Không kết nối được Ollama")
                yield {"type": "token", "content": "Xin lỗi, không kết nối được AI."}
                return
            except httpx.TimeoutException:
                self.log.error("❌ Ollama timeout")
                yield {"type": "token", "content": "Xin lỗi, AI phản hồi quá chậm."}
                return
            except Exception as e:
                self.log.exception(f"❌ LLM lỗi: {e}")
                yield {"type": "token", "content": "Xin lỗi, có lỗi xảy ra."}
                return

            if not tool_calls_buffer:
                return

            # Dedup tool calls theo tên
            seen = {}
            for tc in tool_calls_buffer:
                name = tc.get("function", {}).get("name")
                if name and name not in seen:
                    seen[name] = tc
            tool_calls = list(seen.values())

            self.log.info(f"🔧 LLM gọi {len(tool_calls)} tool(s) (iter {iteration + 1})")
            messages.append({
                "role": "assistant",
                "content": content_buffer,
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = call["function"]["arguments"]
                # ✅ Sinh ID nếu Ollama không cấp
                call_id = call.get("id") or f"call_{fn_name}_{iteration}"

                yield {"type": "tool", "name": fn_name, "args": fn_args}

                result = await self._execute_tool(fn_name, fn_args)
                self.log.info(f"   ← {fn_name}: {result[:100]}")
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": call_id,
                })

        self.log.warning(f"⚠️ Vượt quá {max_iter} iterations")
        yield {"type": "token", "content": "Xin lỗi, tôi không xử lý được yêu cầu."}

    async def _execute_tool(self, name: str, arguments) -> str:
        from app.core.providers.tools.registry import execute_tool
        return await execute_tool(name, arguments)


ProviderRegistry.register_llm("ollama", OllamaProvider)
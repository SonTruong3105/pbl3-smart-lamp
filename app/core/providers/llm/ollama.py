"""Ollama LLM provider"""
from __future__ import annotations
import json
from typing import AsyncGenerator, List, Optional
import httpx
from app.core.providers.base import LLMProviderBase, ProviderRegistry

class OllamaProvider(LLMProviderBase):
    async def response(self, messages: List[dict]) -> AsyncGenerator[str, None]:
        async for item in self._chat_stream_internal(messages, tools=None):
            if item.get("type") == "token": yield item["content"]

    async def response_with_functions(self, messages: List[dict], tools: Optional[List[dict]] = None) -> AsyncGenerator[dict, None]:
        async for item in self._chat_stream_internal(messages, tools=tools):
            yield item

    async def chat_stream(self, messages, tools=None) -> AsyncGenerator[dict, None]:
        async for item in self.response_with_functions(messages, tools): yield item

    async def _chat_stream_internal(self, messages: List[dict], tools: Optional[List[dict]]) -> AsyncGenerator[dict, None]:
        url = self.config.get("url")
        model = self.config.get("model")
        timeout = self.config.get("request_timeout", 120.0)
        
        options = {"temperature": self.config.get("temperature", 0.7), "num_predict": self.config.get("num_predict", 512)}
        if self.config.get("num_ctx") is not None: options["num_ctx"] = self.config.get("num_ctx")
        if self.config.get("num_batch") is not None: options["num_batch"] = self.config.get("num_batch")

        payload = {"model": model, "messages": messages, "stream": True, "think": self.config.get("think", False), "options": options}
        if self.config.get("keep_alive") is not None: payload["keep_alive"] = self.config.get("keep_alive")
        if tools: payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        self.log.error(f"❌ Ollama HTTP {r.status_code}: {body[:200]!r}")
                    r.raise_for_status()

                    async for line in r.aiter_lines():
                        if not line.strip(): continue
                        try: chunk = json.loads(line)
                        except json.JSONDecodeError: continue
                        msg = chunk.get("message", {})
                        tok = msg.get("content")
                        if tok: yield {"type": "token", "content": tok}
                        for tc in msg.get("tool_calls") or []:
                            fn = tc.get("function", {})
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try: args = json.loads(args) if args else {}
                                except Exception: args = {}
                            yield {"type": "tool_call", "id": tc.get("id") or "call_x", "name": fn.get("name"), "arguments": args}
                        if chunk.get("done"): break
        except Exception as e:
            self.log.error(f"❌ Ollama lỗi: {e}")
            raise e

ProviderRegistry.register_llm("ollama", OllamaProvider)

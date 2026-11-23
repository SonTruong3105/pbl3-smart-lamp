"""Ollama LLM provider - Optimized with Connection Pooling"""
from __future__ import annotations
import json
from typing import AsyncGenerator, List, Optional
import httpx
from app.core.providers.base import LLMProviderBase, ProviderRegistry

_http_clients = {}
def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in _http_clients:
        _http_clients[timeout] = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_keepalive_connections=10, max_connections=100))
    return _http_clients[timeout]

class OllamaProvider(LLMProviderBase):
    async def response(self, messages: List[dict]) -> AsyncGenerator[str, None]:
        async for item in self._chat_stream_internal(messages, tools=None):
            if item.get("type") == "token": yield item["content"]

    async def response_with_functions(self, messages: List[dict], tools: Optional[List[dict]] = None) -> AsyncGenerator[dict, None]:
        async for item in self._chat_stream_internal(messages, tools=tools):
            yield item

    async def _chat_stream_internal(self, messages: List[dict], tools: Optional[List[dict]]) -> AsyncGenerator[dict, None]:
        url = self.config.get("url")
        model = self.config.get("model")
        timeout = self.config.get("request_timeout", 120.0)
        
        options = {
            "temperature": self.config.get("temperature", 0.7), 
            "num_predict": self.config.get("num_predict", 512),
            "num_gpu": self.config.get("num_gpu", 99),
            "num_ctx": self.config.get("num_ctx", 2048),
        "num_keep": self.config.get("num_keep", 4),
        }
        if self.config.get("num_batch") is not None: options["num_batch"] = self.config.get("num_batch")
        for key in ("top_k", "top_p", "repeat_penalty"):
            if self.config.get(key) is not None: options[key] = self.config[key]

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": self.config.get("think", False),
            "keep_alive": self.config.get("keep_alive", -1),
            "options": options,
        }
        if tools: payload["tools"] = tools

        try:
            client = get_http_client(timeout)
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
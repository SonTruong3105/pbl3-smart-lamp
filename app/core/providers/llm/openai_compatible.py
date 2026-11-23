"""Provider cho các API tương thích OpenAI"""
import asyncio
import os
from openai import AsyncOpenAI
from app.core.providers.base import LLMProviderBase, ProviderRegistry

class OpenAICompatibleProvider(LLMProviderBase):
    def __init__(self, config, tools_schema=None, log=None):
        super().__init__(config, tools_schema, log)
        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.get("base_url", "https://api.openai.com/v1"),
            timeout=float(config.get("request_timeout", 30.0)),
            max_retries=0,
        )
        self._concurrency = asyncio.Semaphore(
            max(1, int(config.get("max_concurrency", 4)))
        )

    async def response_with_functions(self, messages, tools=None):
        """Stream text; assemble fragmented OpenAI tool-call deltas by index."""
        async with self._concurrency:
            try:
                payload = {
                    "model": self.config.get("model"),
                    "messages": messages,
                    "stream": True,
                    "temperature": self.config.get("temperature", 0.1),
                    "max_tokens": self.config.get("num_predict", 256),
                }
                if tools:
                    payload["tools"] = tools
                if "groq.com" in str(self.client.base_url):
                    payload["extra_body"] = {"reasoning_effort": "none"}

                stream = await self.client.chat.completions.create(**payload)
                assembled = {}
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield {"type": "token", "content": delta.content}
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            slot = assembled.setdefault(idx, {
                                "id": "", "name": "", "arguments": ""
                            })
                            if tc.id:
                                slot["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    slot["name"] += tc.function.name
                                if tc.function.arguments:
                                    slot["arguments"] += tc.function.arguments

                for idx in sorted(assembled):
                    item = assembled[idx]
                    if not item["id"]:
                        item["id"] = f"call_{idx}"
                    yield {
                        "type": "tool_call",
                        "id": item["id"],
                        "name": item["name"],
                        "arguments": item["arguments"] or "{}",
                    }
            except Exception as e:
                self.log.error(f"API lỗi: {e}")
                raise

ProviderRegistry.register_llm("openai_compatible", OpenAICompatibleProvider)

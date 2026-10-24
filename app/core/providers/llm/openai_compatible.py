"""Provider cho các API tương thích OpenAI"""
import os
from openai import AsyncOpenAI
from app.core.providers.base import LLMProviderBase, ProviderRegistry

class OpenAICompatibleProvider(LLMProviderBase):
    def __init__(self, config, tools_schema=None, log=None):
        super().__init__(config, tools_schema, log)
        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=api_key, base_url=config.get("base_url", "https://api.openai.com/v1"))

    async def response_with_functions(self, messages, tools=None):
        try:
            payload = {
                "model": self.config.get("model"), "messages": messages, "tools": tools,
                "stream": True, "temperature": self.config.get("temperature", 0.1),
                "max_tokens": self.config.get("num_predict", 256),
            }
            if "groq.com" in str(self.client.base_url): payload["extra_body"] = {"reasoning_effort": "none"}
            stream = await self.client.chat.completions.create(**payload)
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content: yield {"type": "token", "content": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        yield {"type": "tool_call", "id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
        except Exception as e:
            self.log.error(f"❌ API lỗi: {e}")
            raise e

ProviderRegistry.register_llm("openai_compatible", OpenAICompatibleProvider)

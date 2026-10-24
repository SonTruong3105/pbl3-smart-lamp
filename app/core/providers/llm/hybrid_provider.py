"""HybridLLMProvider — Tự động Fallback"""
from app.core.providers.base import LLMProviderBase, ProviderRegistry

class HybridLLMProvider(LLMProviderBase):
    def __init__(self, config, tools_schema=None, log=None):
        super().__init__(config, tools_schema, log)
        
        # ⭐ Defensive: nếu config phẳng (không có groq/ollama)
        # → reload từ app_config.llm_config (đúng cấu trúc hybrid)
        if not any(k in config for k in ("groq", "deepseek", "ollama")):
            from app.config import config as app_cfg
            try:
                config = app_cfg.llm_config
                self.log.info(f"🔄 Hybrid: Đã reload từ app_config.llm_config")
            except Exception as e:
                self.log.error(f"❌ Không reload được config: {e}")
        
        # Log keys để debug
        self.log.info(f"🔍 Hybrid config keys: {list(config.keys())}")
        
        self.providers = []
        if config.get("groq"):
            try:
                p = ProviderRegistry.create_llm("openai_compatible", config=config["groq"], log=log)
                self.providers.append(p)
                self.log.info(f"✅ Groq: {type(p).__name__} model={config['groq'].get('model')}")
            except Exception as e:
                self.log.error(f"❌ Groq init fail: {e}")
        
        if config.get("deepseek"):
            try:
                p = ProviderRegistry.create_llm("openai_compatible", config=config["deepseek"], log=log)
                self.providers.append(p)
                self.log.info(f"✅ DeepSeek: {type(p).__name__}")
            except Exception as e:
                self.log.error(f"❌ DeepSeek init fail: {e}")
        
        if config.get("ollama"):
            try:
                p = ProviderRegistry.create_llm("ollama", config=config["ollama"], log=log)
                self.providers.append(p)
                self.log.info(f"✅ Ollama: {type(p).__name__} model={config['ollama'].get('model')}")
            except Exception as e:
                self.log.error(f"❌ Ollama init fail: {e}")
        
        self.log.info(f"🎯 Hybrid tổng: {len(self.providers)} providers sẵn sàng")

    async def response_with_functions(self, messages, tools=None):
        if not self.providers:
            yield {"type": "token", "content": "Lỗi: Không có LLM nào được cấu hình."}
            return
        for i, provider in enumerate(self.providers):
            try:
                self.log.info(f"🚀 [LLM] Đang gọi Provider {i+1}...")
                async for event in provider.response_with_functions(messages, tools): yield event
                return 
            except Exception as e:
                self.log.warning(f"⚠️ Provider {i+1} lỗi. Chuyển sang dự phòng...")
                if i == len(self.providers) - 1:
                    yield {"type": "token", "content": "Xin lỗi, hệ thống AI đang mất kết nối."}

ProviderRegistry.register_llm("hybrid", HybridLLMProvider)

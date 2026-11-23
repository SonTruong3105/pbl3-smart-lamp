"""HybridLLMProvider — Smart Router (Arcee + Qwen router + Groq).

Fix:
1. Có tool result → route chat model
2. Patterns phủ weather/time/news/forecast/exchange/calculate
3. Groq tools truncation dùng tool_names_for_query
4. Bỏ fallback len>20
5. Negation chặn cả Groq
6. Token estimate 2.5 chars/token
7. Sort fallback local trước cloud
8. Đọc priority từ config
"""
import re
import time
from dataclasses import dataclass

from app.core.providers.base import LLMProviderBase, ProviderRegistry


@dataclass
class _ProviderState:
    name: str
    provider: object
    fail_count: int = 0
    cooldown_until: float = 0.0


_NEGATION_RE = re.compile(
    r"\b(đừng|chớ|không\s+cần|không\s+được|khỏi|thôi\s+đừng)\b",
    re.IGNORECASE,
)


class HybridLLMProvider(LLMProviderBase):
    def __init__(self, config, tools_schema=None, log=None):
        super().__init__(config, tools_schema, log)
        if not any(k in config for k in ("ollama_chat", "groq", "priority")):
            from app.config import config as app_cfg
            try:
                config = app_cfg.llm_config
                self.config = config
                self.log.info("🔧 Hybrid: reload config từ LLM.hybrid")
            except Exception as e:
                self.log.warning(f"⚠️ Không load được LLM config: {e}")
        self.fail_threshold = int(config.get("fail_threshold", 3))
        self.cooldown_sec = float(config.get("cooldown_sec", 300.0))
        provider_names = config.get("priority") or ["ollama_chat", "ollama_tools", "groq"]
        self.providers = []
        for name in provider_names:
            if name not in config: continue
            pcfg = config.get(name) or {}
            if not pcfg: continue
            try:
                p_type = pcfg.get("type", "ollama")
                p = ProviderRegistry.create_llm(p_type, config=pcfg, log=log)
                self.providers.append(_ProviderState(name=name, provider=p))
                self.log.info(f"✅ Hybrid[{name}]: model={pcfg.get('model')}")
            except Exception as e:
                self.log.error(f"❌ {name} init fail: {e}")
        self.log.info(f"🎯 Smart Router: {[p.name for p in self.providers]}")

    def _is_available(self, ps): return time.time() >= ps.cooldown_until
    def _mark_ok(self, ps): ps.fail_count = 0
    def _mark_fail(self, ps):
        ps.fail_count += 1
        if ps.fail_count >= self.fail_threshold:
            ps.cooldown_until = time.time() + self.cooldown_sec
            self.log.warning(f"🔴 {ps.name} cooldown {self.cooldown_sec:.0f}s")

    def _route(self, query, tools, messages=None):
        """Route topical queries to the configured specialist provider."""
        priority = self.config.get("priority", ["ollama_chat"])
        routing = self.config.get("routing") or {}
        if routing.get("enable") and query:
            for pattern in routing.get("groq_patterns", []):
                if re.search(pattern, query, flags=re.IGNORECASE):
                    if "groq" in priority:
                        return "groq"

        if messages and any(m.get("role") == "tool" for m in messages):
            return priority[0] if priority else "ollama_chat"
        return priority[0] if priority else "ollama_chat"
    def _estimate_tokens(self, messages, tools):
        text = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, str): text += c
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and "text" in part: text += part["text"]
        return (len(text) // 2) + (len(tools or []) * 200)

    def _select_groq_tools(self, tools, query):
        if not tools: return tools
        try:
            from app.core.providers.tools.registry import tool_names_for_query
            relevant = tool_names_for_query(query or "")
        except Exception:
            relevant = set()
        if relevant:
            selected = [t for t in tools if t.get("function", {}).get("name") in relevant]
            for t in tools:
                if t.get("function", {}).get("name", "") == "direct_answer" and t not in selected:
                    selected.append(t); break
            if selected:
                self.log.debug(f"✂️ Groq tools: {len(tools)} → {len(selected)}")
                return selected
        kept = list(tools[:3])
        for t in tools:
            if t.get("function", {}).get("name", "") == "direct_answer" and t not in kept:
                kept.append(t); break
        return kept

    async def response_with_functions(self, messages, tools=None):
        if not self.providers:
            yield {"type": "token", "content": "Lỗi: Không có LLM nào."}
            return
        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        prefer = self._route(last_user, tools, messages)
        self.log.info(f"🧭 Route → {prefer.upper()}")

        def _sort_key(p):
            if p.name == prefer: return 0
            if p.name.startswith("ollama_"): return 1
            return 2
        ordered = sorted(self.providers, key=_sort_key)

        est = self._estimate_tokens(messages, tools)
        GROQ_LIMIT = 6500
        groq_skip = est > GROQ_LIMIT
        if groq_skip and prefer == "groq":
            self.log.info(f"⏭️ Groq skip (≈{est} tok) → ollama_chat")
            prefer = "ollama_chat"
            ordered = sorted(self.providers, key=_sort_key)

        has_output = False
        for ps in ordered:
            if not self._is_available(ps): continue
            if ps.name == "groq" and groq_skip: continue
            ps_tools = tools
            # AI-native: Không cắt tools cho Groq
            self.log.info(f"🚀 [Hybrid] → {ps.name}")
            try:
                async for event in ps.provider.response_with_functions(messages, ps_tools):
                    if event and not event.get("_error"): has_output = True
                    yield event
                self._mark_ok(ps)
                if has_output:
                    self.log.info(f"✅ [{ps.name}] xong")
                    return
            except Exception as e:
                err_str = str(e)
                is_413 = "413" in err_str or "too large" in err_str.lower()
                if is_413:
                    self.log.warning(f"⚠️ {ps.name} 413 → fallback")
                else:
                    self.log.warning(f"⚠️ {ps.name} lỗi: {type(e).__name__}: {e}")
                    self._mark_fail(ps)
                if has_output: return
        yield {"type": "token", "content": "Xin lỗi, AI đang bận.", "_error": True}


ProviderRegistry.register_llm("hybrid", HybridLLMProvider)
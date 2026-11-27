"""HybridLLMProvider — Smart Router (Ollama local + Groq cloud kèm auto-escalate)."""
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
_ESCALATE_MARKER = "[ESCALATE_GROQ]"


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
            if name not in config:
                continue
            pcfg = config.get(name) or {}
            if not pcfg:
                continue
            try:
                p_type = pcfg.get("type", "ollama")
                p = ProviderRegistry.create_llm(p_type, config=pcfg, log=log)
                self.providers.append(_ProviderState(name=name, provider=p))
                self.log.info(f"✅ Hybrid[{name}]: model={pcfg.get('model')}")
            except Exception as e:
                self.log.error(f"❌ {name} init fail: {e}")
        self.log.info(f"🎯 Smart Router: {[p.name for p in self.providers]}")

    def _is_available(self, ps):
        return time.time() >= ps.cooldown_until

    def _mark_ok(self, ps):
        ps.fail_count = 0

    def _mark_fail(self, ps):
        ps.fail_count += 1
        if ps.fail_count >= self.fail_threshold:
            ps.cooldown_until = time.time() + self.cooldown_sec
            self.log.warning(f"🔴 {ps.name} cooldown {self.cooldown_sec:.0f}s")

    def _route(self, query, tools, messages=None):
        """Route topical queries or groq_tools to Groq."""
        priority = self.config.get("priority", ["ollama_chat"])
        routing = self.config.get("routing") or {}
        if routing.get("enable") and "groq" in priority:
            groq_tools = set(routing.get("groq_tools") or [])
            if groq_tools and tools:
                tool_names = {
                    (t.get("function") or {}).get("name") or t.get("name", "")
                    for t in tools
                    if isinstance(t, dict)
                }
                if tool_names & groq_tools:
                    return "groq"

            if query and not _NEGATION_RE.search(query):
                for pattern in routing.get("groq_patterns", []):
                    if re.search(pattern, query, flags=re.IGNORECASE):
                        return "groq"

        if messages and any(m.get("role") == "tool" for m in messages):
            return priority[0] if priority else "ollama_chat"
        return priority[0] if priority else "ollama_chat"

    def _estimate_tokens(self, messages, tools):
        text = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                text += c
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and "text" in part:
                        text += part["text"]
        return (len(text) // 2) + (len(tools or []) * 200)

    def _select_groq_tools(self, tools, query):
        if not tools:
            return tools
        try:
            from app.core.providers.tools.registry import tool_names_for_query
            relevant = tool_names_for_query(query or "")
        except Exception:
            relevant = set()
        if relevant:
            selected = [t for t in tools if t.get("function", {}).get("name") in relevant]
            for t in tools:
                if t.get("function", {}).get("name", "") == "direct_answer" and t not in selected:
                    selected.append(t)
                    break
            if selected:
                self.log.debug(f"✂️ Groq tools: {len(tools)} → {len(selected)}")
                return selected
        kept = list(tools[:3])
        for t in tools:
            if t.get("function", {}).get("name", "") == "direct_answer" and t not in kept:
                kept.append(t)
                break
        return kept

    def _ensure_web_search_tool(self, tools):
        """Gắn thêm web_search khi local model báo không biết và đẩy lên Groq."""
        current = list(tools or [])
        if any((t.get("function") or {}).get("name") == "web_search" for t in current if isinstance(t, dict)):
            return current
        try:
            from app.core.providers.tools.unified import FunctionRegistry
            ws_tools = FunctionRegistry({"web_search"}).to_openai_schema()
            return current + ws_tools
        except Exception:
            return current

    async def response_with_functions(self, messages, tools=None):
        if not self.providers:
            yield {"type": "token", "content": "Lỗi: Không có LLM nào."}
            return
        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        prefer = self._route(last_user, tools, messages)
        self.log.info(f"🧭 Route → {prefer.upper()}")

        def _sort_key(p):
            if p.name == prefer:
                return 0
            if p.name.startswith("ollama_"):
                return 1
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
        escalated = False

        for ps in ordered:
            if not self._is_available(ps):
                continue
            if ps.name == "groq" and groq_skip:
                continue

            active_tools = self._ensure_web_search_tool(tools) if (ps.name == "groq" and escalated) else tools
            ps_tools = self._select_groq_tools(active_tools, last_user) if ps.name == "groq" else active_tools
            self.log.info(f"🚀 [Hybrid] → {ps.name}")

            try:
                check_escalate = ps.name.startswith("ollama_") and any(
                    p.name == "groq" and self._is_available(p) for p in ordered
                )
                probe_buf = ""
                probe_released = not check_escalate
                did_escalate = False

                async for event in ps.provider.response_with_functions(messages, ps_tools):
                    if not event:
                        continue
                    if event.get("_error"):
                        yield event
                        continue

                    etype = event.get("type")
                    if not probe_released:
                        if etype == "tool_call":
                            probe_released = True
                            if probe_buf:
                                has_output = True
                                yield {"type": "token", "content": probe_buf}
                                probe_buf = ""
                            has_output = True
                            yield event
                            continue

                        if etype == "token":
                            probe_buf += event.get("content", "")
                            stripped = probe_buf.lstrip()
                            if _ESCALATE_MARKER in stripped:
                                self.log.info(f"🔀 [{ps.name}] không chắc chắn ({_ESCALATE_MARKER}) → đẩy lên GROQ")
                                did_escalate = True
                                escalated = True
                                break
                            # Nếu không bắt đầu bằng '[' hoặc đã vượt quá độ dài marker mà không khớp -> xả buffer
                            if (stripped and not stripped.startswith("[")) or len(stripped) > len(_ESCALATE_MARKER) + 4:
                                probe_released = True
                                has_output = True
                                yield {"type": "token", "content": probe_buf}
                                probe_buf = ""
                            continue

                    has_output = True
                    yield event

                if did_escalate:
                    self._mark_ok(ps)
                    continue

                if not probe_released and probe_buf:
                    if _ESCALATE_MARKER in probe_buf:
                        self.log.info(f"🔀 [{ps.name}] không chắc chắn ({_ESCALATE_MARKER}) → đẩy lên GROQ")
                        escalated = True
                        self._mark_ok(ps)
                        continue
                    has_output = True
                    yield {"type": "token", "content": probe_buf}

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
                if has_output:
                    return

        yield {"type": "token", "content": "Xin lỗi, AI đang bận.", "_error": True}


ProviderRegistry.register_llm("hybrid", HybridLLMProvider)
"""Dialogue manager."""
import uuid
from typing import List, Dict, Optional
from datetime import datetime


class Message:
    def __init__(self, role, content=None, uniq_id=None,
                 tool_calls=None, tool_call_id=None, is_temporary=False):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.is_temporary = is_temporary

    def to_dict(self) -> dict:
        d = {"role": self.role}
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
            if self.content:
                d["content"] = self.content
        elif self.role == "tool":
            if not self.tool_call_id:
                return {"role": "tool", "content": self.content or ""}
            d["tool_call_id"] = self.tool_call_id
            d["content"] = self.content
        else:
            d["content"] = self.content
        return d


class Dialogue:
    def __init__(self):
        self.dialogue: List[Message] = []

    def put(self, message: Message):
        self.dialogue.append(message)

    def clear(self):
        self.dialogue.clear()

    def __len__(self):
        return len(self.dialogue)

    def _ensure_tool_calls_complete(self) -> List[Message]:
        responded = set()
        for msg in self.dialogue:
            if msg.role == "tool" and msg.tool_call_id:
                responded.add(msg.tool_call_id)

        result: List[Message] = []
        for msg in self.dialogue:
            result.append(msg)
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = (
                        tc.get("id") if isinstance(tc, dict)
                        else getattr(tc, "id", None)
                    )
                    if tc_id and tc_id not in responded:
                        result.append(Message(
                            role="tool",
                            content='{"status": "interrupted"}',
                            tool_call_id=tc_id,
                            is_temporary=True,
                        ))
                        responded.add(tc_id)   # ✅ FIX: tránh duplicate
        return result

    def to_llm_messages(self, memory_str=None, system_prompt=None, max_turns=20):
        complete = self._ensure_tool_calls_complete()
        if len(complete) > max_turns:
            complete = complete[-max_turns:]

        messages = [m.to_dict() for m in complete]

        if system_prompt:
            full_prompt = system_prompt
            if memory_str:
                full_prompt += f"\n\n[Memory]\n{memory_str}"
            full_prompt = full_prompt.replace(
                "{{current_time}}",
                datetime.now().strftime("%H:%M %d/%m/%Y"),
            )
            messages.insert(0, {"role": "system", "content": full_prompt})

        return messages

    def append_user(self, text: str):
        self.put(Message(role="user", content=text))

    def append_assistant(self, text: str, tool_calls=None):
        self.put(Message(role="assistant", content=text, tool_calls=tool_calls))

    def append_tool(self, content: str, tool_call_id: str):
        self.put(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def last_assistant(self) -> Optional[Message]:
        for m in reversed(self.dialogue):
            if m.role == "assistant" and m.content:
                return m
        return None
from typing import Any, Literal
from pydantic import BaseModel, Field

class HelloMessage(BaseModel):
    type: Literal["hello"]
    device_id: str = Field(default="browser-anon", min_length=1, max_length=128)
    session_id: int | None = None
    force_new: bool = False

class TextMessage(BaseModel):
    type: Literal["message"]
    text: str = Field(min_length=1, max_length=4000)

class ClearSessionMessage(BaseModel):
    type: Literal["clear_session"]

class OutboundMessage(BaseModel):
    type: str
    payload: dict[str, Any] | None = None

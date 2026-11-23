"""ContextVar expose current ConnectionHandler cho tool funcs.
ServerPluginExecutor calls item.func(**args) — không truyền conn.
Dùng ContextVar (giống AI Chatbot _request_preferences) để tool đọc conn.
"""
from contextvars import ContextVar
from typing import Any, Optional
_current: ContextVar[Optional[Any]] = ContextVar("current_conn", default=None)
def set_connection(conn): return _current.set(conn)
def get_connection(): return _current.get()
def reset_connection(tok): _current.reset(tok)
import asyncio

import httpx
import pytest

from app.core.providers.asr import phowhisper
from app.core.providers.asr.phowhisper import PhoWhisperProvider


class _Log:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "xin chào"}


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response or _Response()
        self.error = error
        self.calls = []
        self.is_closed = False

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response

    async def aclose(self):
        self.is_closed = True


def test_transcribe_applies_timeout_per_request_and_reuses_client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(phowhisper, "_asr_client", fake)
    provider = PhoWhisperProvider({
        "url": "http://asr.test/v1/audio/transcriptions",
        "model": "chunkformer-vie",
        "language": "vi",
        "request_timeout": 17,
    }, log=_Log())

    result = asyncio.run(provider.transcribe(b"wav"))
    assert result == "xin chào"
    args, kwargs = fake.calls[0]
    assert args[0] == "http://asr.test/v1/audio/transcriptions"
    assert kwargs["timeout"] == httpx.Timeout(17.0)
    assert kwargs["data"] == {"language": "vi", "model": "chunkformer-vie"}
    assert phowhisper._get_client() is fake


def test_transcribe_timeout_returns_empty(monkeypatch):
    fake = _FakeClient(error=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(phowhisper, "_asr_client", fake)
    provider = PhoWhisperProvider({"url": "http://asr.test", "request_timeout": 2}, log=_Log())
    assert asyncio.run(provider.transcribe(b"wav")) == ""


def test_close_asr_client_closes_and_clears_global(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(phowhisper, "_asr_client", fake)
    asyncio.run(phowhisper.close_asr_client())
    assert fake.is_closed
    assert phowhisper._asr_client is None


def test_transcribe_rejects_invalid_response_shape(monkeypatch):
    class InvalidResponse(_Response):
        def json(self):
            return {"text": ["not", "a string"]}

    monkeypatch.setattr(phowhisper, "_asr_client", _FakeClient(response=InvalidResponse()))
    provider = PhoWhisperProvider({"url": "http://asr.test"}, log=_Log())
    assert asyncio.run(provider.transcribe(b"wav")) == ""

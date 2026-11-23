import asyncio

from app.core.routing.fast_track import process_fast_track


class _Log:
    def warning(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class _Result:
    def __init__(self, action=None, response="ok", result="ok"):
        from app.core.providers.tools.unified.register import Action
        action = Action.RESPONSE if action is None else action
        self.action = action
        self.response = response
        self.result = result


def test_negated_lamp_intent_never_calls_tool():
    async def run():
        calls = []
        replies = []

        async def execute(name, args):
            calls.append((name, args))
            return _Result()

        async def quick(user, reply):
            replies.append((user, reply))
            return reply

        result = await process_fast_track("Đừng bật đèn", quick, _Log(), execute)
        assert result == "Được, mình sẽ không thực hiện lệnh điều khiển đèn đó."
        assert replies and "không thực hiện" in replies[0][1]
        assert calls == []

    asyncio.run(run())


def test_negated_turn_off_request_is_not_executed():
    async def run():
        calls = []

        async def execute(name, args):
            calls.append((name, args))
            return _Result()

        async def quick(_user, reply):
            return reply

        result = await process_fast_track("Không tắt đèn", quick, _Log(), execute)
        assert "không thực hiện" in result
        assert calls == []

    asyncio.run(run())


def test_positive_lamp_command_executes_expected_tool():
    async def run():
        calls = []

        async def execute(name, args):
            calls.append((name, args))
            return _Result(response="Đã bật đèn.")

        async def quick(_user, reply):
            return reply

        result = await process_fast_track("Bật đèn", quick, _Log(), execute)
        assert result == "Đã bật đèn."
        assert calls == [("control_light", {"action": "on"})]

    asyncio.run(run())


def test_negated_music_request_never_calls_tool():
    async def run():
        calls = []

        async def execute(name, args):
            calls.append((name, args))
            return _Result()

        async def quick(_user, reply):
            return reply

        result = await process_fast_track("Đừng phát bài Nối vòng tay lớn", quick, _Log(), execute)
        assert result is None
        assert calls == []

    asyncio.run(run())


def test_natural_language_about_light_is_not_fast_tracked():
    async def run():
        calls = []

        async def execute(name, args):
            calls.append((name, args))
            return _Result()

        async def quick(_user, reply):
            return reply

        result = await process_fast_track("Không bật đèn thì phòng tối", quick, _Log(), execute)
        assert result is not None
        assert calls == []

    asyncio.run(run())


def test_natural_language_math_keyword_is_not_calculated():
    async def run():
        replies = []

        async def quick(_user, reply):
            replies.append(reply)
            return reply

        result = await process_fast_track("Tôi trừ tiền trong tài khoản", quick, _Log())
        assert result is None
        assert replies == []

    asyncio.run(run())


def test_time_and_weekday_fast_track_only_standalone_questions(monkeypatch):
    async def run():
        replies = []

        async def quick(_user, reply):
            replies.append(reply)
            return reply

        async def execute(_name, _args):
            return _Result()

        assert await process_fast_track("Mấy giờ rồi?", quick, _Log(), execute)
        assert await process_fast_track("Hôm nay thứ mấy?", quick, _Log(), execute)
        assert await process_fast_track("Tôi hỏi mấy giờ xe đến", quick, _Log(), execute) is None
        assert await process_fast_track("Hôm nay thứ mấy mình đi làm?", quick, _Log(), execute) is None
        assert len(replies) == 2

    asyncio.run(run())


def test_device_intent_classifier_blocks_negated_control(monkeypatch):
    from app.core.providers.intent.intent_llm import IntentLLMProvider

    monkeypatch.setattr(IntentLLMProvider, "_classify", lambda *_a, **_k: None)
    provider = object.__new__(IntentLLMProvider)
    provider.log = _Log()
    result = asyncio.run(provider.detect_intent_full(object(), "Đừng bật đèn"))
    assert result.intent == "chat"
    assert result.tool is None


def test_calendar_intent_and_tool_schema_cover_today_query():
    from app.core.providers.intent.intent_llm import IntentLLMProvider
    from app.core.routing.intent_filter import build_tool_schema

    provider = object.__new__(IntentLLMProvider)
    provider.log = _Log()
    result = asyncio.run(provider.detect_intent_full(object(), "lịch trình hôm nay"))
    assert result.intent == "calendar"
    assert result.tool == "list_calendar"

    names = {tool["function"]["name"] for tool in build_tool_schema("lịch trình hôm nay")}
    assert "list_calendar" in names


def test_calendar_write_tool_schema_is_gated_by_calendar_terms():
    from app.core.routing.intent_filter import build_tool_schema

    names = {tool["function"]["name"] for tool in build_tool_schema(
        "thêm lịch đi học ngày mai"
    )}
    assert {"list_calendar", "add_calendar_event"} <= names
    unrelated_names = {tool["function"]["name"] for tool in build_tool_schema(
        "thêm bài vào danh sách"
    )}
    assert "add_calendar_event" not in unrelated_names


def test_farewell_is_fast_tracked_without_speaking_again():
    from app.core.routing.fast_track import process_fast_track

    async def run():
        calls = []

        async def quick(_user, reply):
            calls.append(reply)
            return reply

        reply = await process_fast_track("Tạm biệt nhé", quick, _Log())
        assert reply.startswith("Tạm biệt")
        assert calls == [reply]
        assert await process_fast_track("Tạm biệt, hôm nay lịch thế nào?", quick, _Log()) is None

    asyncio.run(run())


def test_farewell_detector_only_matches_standalone_phrases():
    from app.core.routing.fast_track import FAREWELL_RE
    from app.core.routing.fast_track import _norm

    assert FAREWELL_RE.fullmatch(_norm("Hẹn gặp lại nhé!"))
    assert not FAREWELL_RE.fullmatch(_norm("Tạm biệt, hôm nay tôi có lịch gì?"))

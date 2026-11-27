import asyncio
import json
from types import SimpleNamespace

from app.core import connection as connection_module
from app.core.connection import (
    ConnectionHandler,
    _build_lamp_control_plan,
    _lamp_tool_matches_request,
    _parse_requested_number,
    _requires_lamp_action_confirmation,
    _tool_result_confirms_lamp_action,
)
from app.core.providers.tools.unified import Action, ActionResponse


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def response_with_functions(self, messages, tools=None):
        self.calls += 1
        response = self.responses.pop(0)
        for event in response:
            yield event


class _FakeLog:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


async def _run_chat(responses, tool_result=None, max_iter=2, user_text="tắt đèn"):
    emitted = []
    executed = []
    handler = ConnectionHandler.__new__(ConnectionHandler)
    handler.log = _FakeLog()
    handler.device_id = "test-device"
    handler.llm = _FakeLLM(responses)
    handler.intent_provider = None
    handler._send_callback = lambda _payload: asyncio.sleep(0)
    handler.tool_handler = SimpleNamespace(execute=lambda _conn, name, args: _execute(executed, name, args, tool_result))

    previous = connection_module.config.llm_max_tool_iterations
    connection_module.config.llm_max_tool_iterations = max_iter
    try:
        messages = [{"role": "user", "content": user_text}]
        tools = [{
            "type": "function",
            "function": {
                "name": "Lamp.TurnOff",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }]
        text = await handler.chat_with_tools(messages, tools, on_token=lambda tok: _emit(emitted, tok))
        return text, emitted, executed, handler.llm.calls
    finally:
        connection_module.config.llm_max_tool_iterations = previous


async def _emit(emitted, text, on_token=None):
    emitted.append(text)
    if on_token:
        await on_token(text)


async def _execute(executed, name, args, result):
    executed.append((name, args))
    if isinstance(result, Exception):
        raise result
    return result or ActionResponse(Action.REQLLM, result=json.dumps({"on": False}))


def _lamp_schema(name, properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": properties},
        },
    }


def test_lamp_guard_excludes_negation_and_status_question():
    assert _requires_lamp_action_confirmation("tắt đèn")
    assert not _requires_lamp_action_confirmation("đèn đang bật")
    assert not _requires_lamp_action_confirmation("đèn đang tắt")
    assert not _requires_lamp_action_confirmation("đừng tắt đèn")
    assert not _requires_lamp_action_confirmation("đừng quên tắt đèn")
    assert not _requires_lamp_action_confirmation("đèn đang bật hay tắt?")
    assert not _requires_lamp_action_confirmation("đèn có đang bật không?")
    assert _requires_lamp_action_confirmation("tắt đèn, giảm độ sáng xuống 65 phần trăm")
    assert not _requires_lamp_action_confirmation("có nên bật đèn không?")
    assert not _requires_lamp_action_confirmation("có thể bật đèn giúp tôi không?")


def test_lamp_tool_match_checks_operation_without_selecting_tool():
    assert _lamp_tool_matches_request("tắt đèn, giảm độ sáng xuống 65%", "Lamp.TurnOff")
    assert _lamp_tool_matches_request("tắt đèn, giảm độ sáng xuống 65%", "Lamp.SetBrightness")
    assert _lamp_tool_matches_request("tắt đèn", "Lamp.TurnOff")
    assert not _lamp_tool_matches_request("tắt đèn", "Lamp.TurnOn")
    assert not _lamp_tool_matches_request("tắt đèn", "Lamp.GetState")
    assert _lamp_tool_matches_request(
        "chuyển sang màu trung tính", "self.lights.set_warm_cool",
    )
    assert _lamp_tool_matches_request(
        "đặt độ sáng 65 phần trăm và màu trung tính",
        "self.lights.set_brightness_temp",
    )
    assert not _lamp_tool_matches_request(
        "chuyển sang màu trung tính", "self.lights.set_brightness_temp",
    )
    assert not _lamp_tool_matches_request(
        "chuyển sang màu trung tính", "self.lights.get_state",
    )


def test_vietnamese_lamp_number_parser():
    assert _parse_requested_number("đặt độ sáng 65 phần trăm", percent=True) == 65
    assert _parse_requested_number("đặt độ sáng sáu mươi lăm phần trăm", percent=True) == 65
    assert _parse_requested_number("đặt độ sáng 150%", percent=True) is None
    assert _parse_requested_number("đổi màu 4500K") == 4500


def test_lamp_control_plan_maps_explicit_color_and_brightness_without_llm():
    tools = [
        _lamp_schema("self.lights.set_warm_cool", {
            "warm_percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "cool_percent": {"type": "integer", "minimum": 0, "maximum": 100},
        }),
        _lamp_schema("self.lights.set_brightness_temp", {
            "brightness_percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "kelvin": {"type": "integer", "minimum": 3000, "maximum": 6000},
        }),
    ]

    assert _build_lamp_control_plan("chuyển đèn sang màu trung tính", tools) == (
        [("self.lights.set_warm_cool", {"warm_percent": 50, "cool_percent": 50})],
        "Mình đã chuyển màu sang trung tính.",
    )
    assert _build_lamp_control_plan(
        "đặt độ sáng 65 phần trăm và màu trung tính", tools,
    ) == (
        [("self.lights.set_brightness_temp", {"brightness_percent": 65, "kelvin": 4500})],
        "Mình đã đặt độ sáng 65 phần trăm và chuyển màu sang trung tính.",
    )
    assert _build_lamp_control_plan("đặt độ sáng 150 phần trăm", tools) is None
    assert _build_lamp_control_plan("chỉnh đèn", tools) is None


def test_lamp_result_requires_structured_matching_state():
    assert _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, '{"on": false}')
    assert not _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, '{"on": true}')
    assert not _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, "OK")
    assert not _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, '{"isError": true}')
    assert _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, '{"success": true}')
    assert not _tool_result_confirms_lamp_action("Lamp.TurnOff", {}, '{"success": true, "on": true}')


def test_warm_cool_tool_result_confirmation():
    tool = "self.lights.set_warm_cool"
    assert _tool_result_confirms_lamp_action(
        tool, {"warm_percent": 50, "cool_percent": 50}, "True",
    )
    assert _tool_result_confirms_lamp_action(
        tool, {"warm_percent": 50, "cool_percent": 50},
        '{"warm_percent": 50, "cool_percent": 50}',
    )
    assert not _tool_result_confirms_lamp_action(
        tool, {"warm_percent": 50, "cool_percent": 50},
        "Brightness must be between 0 and 100 percent",
    )
    assert not _tool_result_confirms_lamp_action(
        tool, {"warm_percent": 50, "cool_percent": 50}, "false",
    )


def test_chat_uses_deterministic_lamp_plan_without_calling_small_llm():
    async def run():
        emitted = []
        executed = []
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.log = _FakeLog()
        handler.device_id = "test-device"
        handler.intent_provider = None
        handler.llm = _FakeLLM([])
        handler._send_callback = lambda _payload: asyncio.sleep(0)

        async def execute(_conn, name, args):
            executed.append((name, args))
            return ActionResponse(Action.REQLLM, result="True")

        handler.tool_handler = SimpleNamespace(execute=execute)
        tools = [
            _lamp_schema("self.lights.set_warm_cool", {
                "warm_percent": {"type": "integer", "minimum": 0, "maximum": 100},
                "cool_percent": {"type": "integer", "minimum": 0, "maximum": 100},
            }),
            _lamp_schema("self.lights.set_brightness_temp", {
                "brightness_percent": {"type": "integer", "minimum": 0, "maximum": 100},
                "kelvin": {"type": "integer", "minimum": 3000, "maximum": 6000},
            }),
        ]
        response = await handler.chat_with_tools(
            [{"role": "user", "content": "chuyển đèn sang màu trung tính"}],
            tools,
            on_token=lambda token: _emit(emitted, token),
        )
        return response, emitted, executed, handler.llm.calls

    response, emitted, executed, llm_calls = asyncio.run(run())
    assert response == "Mình đã chuyển màu sang trung tính."
    assert emitted == [response]
    assert executed == [("self.lights.set_warm_cool", {"warm_percent": 50, "cool_percent": 50})]
    assert llm_calls == 0


def test_failed_deterministic_lamp_action_never_reports_success():
    async def run():
        emitted = []
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.log = _FakeLog()
        handler.device_id = "test-device"
        handler.intent_provider = None
        handler.llm = _FakeLLM([])
        handler._send_callback = lambda _payload: asyncio.sleep(0)

        async def execute(_conn, _name, _args):
            return ActionResponse(Action.ERROR, result="device refused")

        handler.tool_handler = SimpleNamespace(execute=execute)
        tools = [_lamp_schema("self.lights.set_warm_cool", {
            "warm_percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "cool_percent": {"type": "integer", "minimum": 0, "maximum": 100},
        })]
        response = await handler.chat_with_tools(
            [{"role": "user", "content": "chuyển đèn sang màu trung tính"}],
            tools,
            on_token=lambda token: _emit(emitted, token),
        )
        return response, emitted, handler.llm.calls

    response, emitted, llm_calls = asyncio.run(run())
    assert response.startswith("Mình chưa thể xác nhận")
    assert emitted == [response]
    assert llm_calls == 0


def test_brightness_temp_tool_confirms_both_requested_categories():
    tool = "self.lights.set_brightness_temp"
    arguments = {"brightness_percent": 65, "kelvin": 4500}
    assert _tool_result_confirms_lamp_action(tool, arguments, "True")
    assert _tool_result_confirms_lamp_action(
        tool, arguments,
        '{"brightness_percent": 65, "kelvin": 4500}',
    )
    assert not _tool_result_confirms_lamp_action(
        tool, arguments, "Invalid brightness or color temperature",
    )
    assert not _tool_result_confirms_lamp_action(
        tool, arguments, '{"brightness_percent": 65, "kelvin": 3000}',
    )


def test_explicit_lamp_command_runs_without_llm_tool_call():
    text, emitted, executed, calls = asyncio.run(
        _run_chat([], max_iter=2, user_text="tắt đèn đi nhé"),
    )
    assert text == "Mình đã tắt đèn."
    assert emitted == [text]
    assert executed == [("Lamp.TurnOff", {})]
    assert calls == 0


def test_direct_lamp_path_reports_failure_without_claiming_success():
    async def run():
        emitted = []
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.log = _FakeLog()
        handler.device_id = "test-device"
        handler.intent_provider = None
        handler._send_callback = lambda _payload: asyncio.sleep(0)
        handler.llm = _FakeLLM([])
        executed = []

        async def execute(_conn, name, args):
            executed.append(name)
            return ActionResponse(Action.ERROR, result="device refused")

        handler.tool_handler = SimpleNamespace(execute=execute)
        tools = [{"type": "function", "function": {"name": "Lamp.TurnOff", "parameters": {"type": "object", "properties": {}}}}]
        result = await handler.chat_with_tools(
            [{"role": "user", "content": "tắt đèn đi nhé"}],
            tools,
            on_token=lambda tok: _emit(emitted, tok),
        )
        return result, emitted, executed

    result, emitted, executed = asyncio.run(run())
    assert result.startswith("Mình chưa thể xác nhận")
    assert executed == ["Lamp.TurnOff"]
    assert emitted == [result]


def test_composite_lamp_command_uses_deterministic_multi_action_plan():
    async def run():
        emitted = []
        executed = []
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.log = _FakeLog()
        handler.device_id = "test-device"
        handler.intent_provider = None
        handler._send_callback = lambda _payload: asyncio.sleep(0)
        handler.llm = _FakeLLM([])

        async def execute(_conn, name, args):
            executed.append((name, args))
            if name == "Lamp.TurnOff":
                return ActionResponse(Action.REQLLM, result='{"on": false}')
            return ActionResponse(Action.REQLLM, result='{"brightness": 65}')

        handler.tool_handler = SimpleNamespace(execute=execute)
        tools = [
            {"type": "function", "function": {"name": "Lamp.TurnOff", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "Lamp.SetBrightness", "parameters": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": []}}},
        ]
        result = await handler.chat_with_tools(
            [{"role": "user", "content": "tắt đèn đi nhé, giảm độ sáng xuống 65 phần trăm"}],
            tools,
            on_token=lambda tok: _emit(emitted, tok),
        )
        return result, emitted, executed

    result, emitted, executed = asyncio.run(run())
    assert result == "Mình đã tắt đèn và đặt độ sáng 65 phần trăm."
    assert executed == [("Lamp.TurnOff", {}), ("Lamp.SetBrightness", {"value": 65})]
    assert emitted == [result]


def test_bad_brightness_arguments_are_not_executed():
    async def run():
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.log = _FakeLog()
        handler.device_id = "test-device"
        handler.intent_provider = None
        handler._send_callback = lambda _payload: asyncio.sleep(0)
        handler.llm = _FakeLLM([])
        executed = []
        handler.tool_handler = SimpleNamespace(execute=lambda _conn, name, args: _execute(
            executed, name, args, ActionResponse(Action.REQLLM, result='{"brightness": 65}'),
        ))
        tools = [{"type": "function", "function": {
            "name": "Lamp.SetBrightness",
            "parameters": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
        }}]
        previous = connection_module.config.llm_max_tool_iterations
        connection_module.config.llm_max_tool_iterations = 1
        try:
            emitted = []
            result = await handler.chat_with_tools(
                [{"role": "user", "content": "giảm độ sáng xuống sáu mươi lăm phần trăm giúp mình"}],
                tools,
                on_token=lambda tok: _emit(emitted, tok),
            )
            return result, emitted, executed
        finally:
            connection_module.config.llm_max_tool_iterations = previous

    result, emitted, executed = asyncio.run(run())
    assert result == "Mình đã đặt độ sáng 65 phần trăm."
    assert emitted == [result]
    assert executed == [("Lamp.SetBrightness", {"value": 65})]

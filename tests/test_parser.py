import json
from types import SimpleNamespace

import pytest

from agent.parser import ModelOutputError, ResponseParser


def make_response(content="", tool_calls=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )


def make_tool_call(call_id: str, name: str, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=arguments,
        ),
    )


def test_parse_plain_assistant_response():
    parsed = ResponseParser().parse(
        make_response(content="done")
    )

    assert parsed.content == "done"
    assert parsed.tool_calls == []
    assert parsed.assistant_message == {
        "role": "assistant",
        "content": "done",
    }


def test_parse_valid_tool_call():
    call = make_tool_call(
        "call-1",
        "write_file",
        json.dumps({"path": "a.py", "content": "print(1)"}),
    )

    parsed = ResponseParser().parse(
        make_response(tool_calls=[call])
    )

    tool_call = parsed.tool_calls[0]
    assert tool_call.is_valid is True
    assert tool_call.id == "call-1"
    assert tool_call.name == "write_file"
    assert tool_call.arguments == {
        "path": "a.py",
        "content": "print(1)",
    }
    assert parsed.assistant_message["tool_calls"][0]["id"] == "call-1"


def test_invalid_json_arguments_become_recoverable_parsed_tool_error():
    call = make_tool_call(
        "call-1",
        "write_file",
        "{not valid json",
    )

    parsed = ResponseParser().parse(
        make_response(tool_calls=[call])
    )

    tool_call = parsed.tool_calls[0]
    assert tool_call.is_valid is False
    assert tool_call.arguments is None
    assert "Invalid JSON arguments" in tool_call.error


def test_non_object_json_arguments_are_rejected():
    call = make_tool_call(
        "call-1",
        "read_file",
        '["a.py"]',
    )

    parsed = ResponseParser().parse(
        make_response(tool_calls=[call])
    )

    assert parsed.tool_calls[0].is_valid is False
    assert "JSON object" in parsed.tool_calls[0].error


def test_missing_choices_raises_model_output_error():
    response = SimpleNamespace(choices=[])

    with pytest.raises(ModelOutputError, match="no choices"):
        ResponseParser().parse(response)


def test_malformed_tool_call_raises_model_output_error():
    malformed = SimpleNamespace(id=None, function=None)

    with pytest.raises(ModelOutputError, match="Malformed tool call"):
        ResponseParser().parse(
            make_response(tool_calls=[malformed])
        )

import json

import pytest

from agent.error_handler import ErrorHandler


def test_model_call_retries_then_succeeds():
    handler = ErrorHandler(
        max_model_retries=2,
        retry_delay_seconds=0,
    )
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert handler.run_model_call(operation) == "ok"
    assert attempts == 3


def test_model_call_raises_after_retry_budget_exhausted():
    handler = ErrorHandler(
        max_model_retries=1,
        retry_delay_seconds=0,
    )

    with pytest.raises(RuntimeError, match="failed after 2 attempt"):
        handler.run_model_call(
            lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )


def test_build_tool_error_returns_json_object():
    result = json.loads(
        ErrorHandler.build_tool_error(
            "bad arguments",
            tool_name="write_file",
        )
    )

    assert result == {
        "ok": False,
        "error": "bad arguments",
        "tool": "write_file",
    }


def test_parse_invalid_json_tool_result():
    result = ErrorHandler.parse_tool_result("not-json")

    assert result["ok"] is False
    assert "invalid JSON" in result["error"]


def test_parse_non_object_tool_result():
    result = ErrorHandler.parse_tool_result("[]")

    assert result["ok"] is False
    assert "JSON object" in result["error"]


def test_parse_result_without_ok_marks_it_as_failure():
    result = ErrorHandler.parse_tool_result('{"stdout": "hello"}')

    assert result["ok"] is False
    assert "does not contain an 'ok' field" in result["error"]

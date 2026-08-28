from agent.state import AgentState
from agent.termination import TerminationAction, TerminationPolicy


def test_state_tracks_write_and_validation_versions():
    state = AgentState()

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True},
    )
    assert state.write_version == 1
    assert state.latest_version_validated is False

    state.record_tool_result(
        "run_command",
        {"purpose": "compile"},
        {"ok": True},
    )
    assert state.latest_version_validated is False

    state.record_tool_result(
        "run_command",
        {"purpose": "test"},
        {"ok": True},
    )
    assert state.validated_version == 1
    assert state.latest_version_validated is True

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True},
    )
    assert state.write_version == 2
    assert state.validated_version == 1
    assert state.latest_version_validated is False


def test_state_tracks_and_resets_consecutive_errors():
    state = AgentState()

    state.record_tool_result(
        "read_file",
        {},
        {"ok": False, "error": "missing"},
    )
    state.record_runtime_error("parser failed")

    assert state.consecutive_errors == 2
    assert state.last_error == "parser failed"

    state.record_tool_result(
        "list_files",
        {},
        {"ok": True},
    )

    assert state.consecutive_errors == 0
    assert state.last_error is None


def test_finish_rejected_before_source_is_written():
    policy = TerminationPolicy(max_steps=5)
    decision = policy.evaluate_finish_request(AgentState())

    assert decision.action == TerminationAction.CONTINUE
    assert decision.reason == "source_not_created"


def test_finish_rejected_when_latest_version_is_not_validated():
    state = AgentState(write_version=1, validated_version=-1)
    policy = TerminationPolicy(max_steps=5)

    decision = policy.evaluate_finish_request(state)

    assert decision.action == TerminationAction.CONTINUE
    assert decision.reason == "latest_version_not_validated"


def test_finish_allowed_after_latest_version_is_validated():
    state = AgentState(write_version=2, validated_version=2)
    policy = TerminationPolicy(max_steps=5)

    decision = policy.evaluate_finish_request(state)

    assert decision.action == TerminationAction.FINISH
    assert decision.can_finish is True


def test_runtime_stops_after_too_many_consecutive_errors():
    state = AgentState(consecutive_errors=3, last_error="boom")
    policy = TerminationPolicy(
        max_steps=5,
        max_consecutive_errors=3,
    )

    decision = policy.evaluate_runtime(state)

    assert decision.action == TerminationAction.STOP
    assert decision.should_stop is True
    assert "boom" in decision.feedback


def test_max_steps_error_contains_limit():
    policy = TerminationPolicy(max_steps=7)

    assert "7" in policy.max_steps_error()


def test_state_restore_restores_durable_and_transient_fields():
    state = AgentState()

    state.restore(
        {
            "step": 4,
            "write_version": 3,
            "validated_version": 2,
            "total_tool_calls": 8,
            "consecutive_errors": 2,
            "last_tool_name": "run_command",
            "last_error": "boom",
        }
    )

    assert state.step == 4
    assert state.write_version == 3
    assert state.validated_version == 2
    assert state.total_tool_calls == 8
    assert state.consecutive_errors == 2
    assert state.last_tool_name == "run_command"
    assert state.last_error == "boom"


def test_prepare_for_resume_only_clears_transient_failure_state():
    state = AgentState(
        step=4,
        write_version=3,
        validated_version=2,
        total_tool_calls=8,
        consecutive_errors=4,
        last_tool_name="run_command",
        last_error="boom",
    )

    state.prepare_for_resume()

    assert state.step == 4
    assert state.write_version == 3
    assert state.validated_version == 2
    assert state.total_tool_calls == 8
    assert state.last_tool_name == "run_command"
    assert state.consecutive_errors == 0
    assert state.last_error is None


def test_state_restore_rejects_inconsistent_versions():
    state = AgentState()

    import pytest

    with pytest.raises(ValueError, match="validated_version"):
        state.restore(
            {
                "write_version": 1,
                "validated_version": 2,
            }
        )


def test_edit_file_marks_latest_source_version_dirty():
    state = AgentState()

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True},
    )
    state.record_tool_result(
        "run_command",
        {"purpose": "test"},
        {"ok": True},
    )

    assert state.latest_version_validated is True
    assert state.write_version == 1
    assert state.validated_version == 1

    state.record_tool_result(
        "edit_file",
        {
            "path": "main.py",
            "old_text": "old",
            "new_text": "new",
        },
        {"ok": True},
    )

    assert state.write_version == 2
    assert state.validated_version == 1
    assert state.latest_version_validated is False

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
        {"ok": True, "purpose": "compile", "validation_eligible": False},
    )
    assert state.latest_version_validated is False

    state.record_tool_result(
        "run_command",
        {"purpose": "test"},
        {"ok": True, "purpose": "test", "validation_eligible": True},
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
        {"ok": True, "purpose": "test", "validation_eligible": True},
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


def test_state_binds_validation_to_workspace_revision():
    state = AgentState()

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True},
        workspace_revision="revision-a",
    )

    state.begin_step(2)
    state.record_tool_result(
        "run_command",
        {
            "argv": ["python", "main.py"],
            "purpose": "test",
        },
        {
            "ok": True,
            "purpose": "run",
            "argv": ["python", "main.py"],
            "validation_eligible": True,
            "returncode": 0,
        },
        workspace_revision="revision-a",
        workspace_revision_before="revision-a",
    )

    assert state.current_revision == "revision-a"
    assert state.validated_revision == "revision-a"
    assert state.latest_version_validated is True
    assert len(state.validation_records) == 1

    record = state.validation_records[0]
    assert record.revision == "revision-a"
    assert record.argv == ["python", "main.py"]
    assert record.purpose == "run"
    assert record.returncode == 0
    assert record.step == 2


def test_revision_change_invalidates_equal_logical_versions():
    state = AgentState(
        write_version=1,
        validated_version=1,
        current_revision="revision-new",
        validated_revision="revision-old",
    )

    assert state.workspace_changed_after_validation is True
    assert state.latest_version_validated is False


def test_failed_command_can_dirty_previously_validated_workspace():
    state = AgentState()

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True},
        workspace_revision="revision-a",
    )
    state.record_tool_result(
        "run_command",
        {
            "argv": ["python", "main.py"],
            "purpose": "test",
        },
        {
            "ok": True,
            "purpose": "run",
            "argv": ["python", "main.py"],
            "validation_eligible": True,
            "returncode": 0,
        },
        workspace_revision="revision-a",
        workspace_revision_before="revision-a",
    )

    assert state.latest_version_validated is True

    state.record_tool_result(
        "run_command",
        {
            "argv": ["python", "mutating_script.py"],
            "purpose": "test",
        },
        {
            "ok": False,
            "returncode": 1,
            "stderr": "failed",
        },
        workspace_revision="revision-b",
    )

    assert state.current_revision == "revision-b"
    assert state.validated_revision == "revision-a"
    assert state.workspace_changed_after_validation is True
    assert state.latest_version_validated is False



def test_successful_command_that_changes_workspace_does_not_validate_new_revision():
    state = AgentState()
    state.begin_step(1)
    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True, "path": "main.py"},
        workspace_revision="revision-a",
    )

    state.begin_step(2)
    state.record_tool_result(
        "run_command",
        {"argv": ["python", "mutate.py"], "purpose": "run"},
        {
            "ok": True,
            "purpose": "run",
            "argv": ["python", "mutate.py"],
            "validation_eligible": True,
            "returncode": 0,
        },
        workspace_revision_before="revision-a",
        workspace_revision="revision-b",
    )

    assert state.current_revision == "revision-b"
    assert state.validated_revision is None
    assert state.validation_records == []
    assert state.latest_version_validated is False


def test_state_restore_restores_revision_validation_evidence():
    state = AgentState()

    state.restore(
        {
            "step": 5,
            "write_version": 2,
            "validated_version": 2,
            "current_revision": "revision-a",
            "validated_revision": "revision-a",
            "validation_records": [
                {
                    "revision": "revision-a",
                    "argv": ["python", "-m", "pytest", "-q"],
                    "purpose": "test",
                    "returncode": 0,
                    "step": 4,
                }
            ],
            "total_tool_calls": 4,
            "consecutive_errors": 0,
            "last_tool_name": "run_command",
            "last_error": None,
        }
    )

    assert state.current_revision == "revision-a"
    assert state.validated_revision == "revision-a"
    assert state.latest_version_validated is True
    assert len(state.validation_records) == 1
    assert state.validation_records[0].step == 4


def test_finish_rejected_when_workspace_changed_after_validation():
    state = AgentState(
        write_version=1,
        validated_version=1,
        current_revision="revision-b",
        validated_revision="revision-a",
    )
    policy = TerminationPolicy(max_steps=5)

    decision = policy.evaluate_finish_request(state)

    assert decision.action == TerminationAction.CONTINUE
    assert decision.reason == "workspace_changed_after_validation"
    assert "stale" in decision.feedback


def test_state_updates_working_memory_from_real_tool_results():
    state = AgentState()
    state.begin_step(1)

    state.record_tool_result(
        "read_file",
        {"path": "src/main.py"},
        {"ok": True, "path": "src/main.py"},
    )

    state.begin_step(2)
    state.record_tool_result(
        "edit_file",
        {
            "path": "src/main.py",
            "old_text": "old",
            "new_text": "new",
        },
        {"ok": True, "path": "src/main.py"},
        workspace_revision="revision-b",
    )

    assert state.working_memory.inspected_files == ["src/main.py"]
    assert state.working_memory.modified_files == ["src/main.py"]
    assert state.working_memory.current_revision == "revision-b"


def test_state_successful_validation_updates_working_memory_evidence():
    state = AgentState()
    state.begin_step(1)

    state.record_tool_result(
        "write_file",
        {"path": "main.py"},
        {"ok": True, "path": "main.py"},
        workspace_revision="revision-a",
    )

    state.begin_step(2)
    state.record_tool_result(
        "run_command",
        {
            "argv": ["python", "main.py"],
            "purpose": "test",
        },
        {
            "ok": True,
            "purpose": "run",
            "argv": ["python", "main.py"],
            "validation_eligible": True,
            "returncode": 0,
        },
        workspace_revision="revision-a",
        workspace_revision_before="revision-a",
    )

    memory = state.working_memory

    assert memory.validation_status == "passed"
    assert memory.current_revision == "revision-a"
    assert memory.validated_revision == "revision-a"
    assert memory.last_validation is not None
    assert memory.last_validation.argv == ["python", "main.py"]
    assert memory.last_validation.step == 2


def test_state_restore_restores_persisted_working_memory():
    state = AgentState()

    state.restore(
        {
            "step": 3,
            "write_version": 1,
            "validated_version": -1,
            "current_revision": "revision-b",
            "validated_revision": None,
            "validation_records": [],
            "working_memory": {
                "inspected_files": ["main.py"],
                "modified_files": ["main.py"],
                "recent_commands": [],
                "last_failed_command": None,
                "last_error": "test failed",
                "current_revision": "revision-b",
                "validated_revision": None,
                "last_validation": None,
            },
            "total_tool_calls": 2,
            "consecutive_errors": 1,
            "last_tool_name": "run_command",
            "last_error": "test failed",
        }
    )

    assert state.working_memory.inspected_files == ["main.py"]
    assert state.working_memory.modified_files == ["main.py"]
    assert state.working_memory.last_error == "test failed"
    assert state.working_memory.current_revision == "revision-b"

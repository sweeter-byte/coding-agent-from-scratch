from agent.working_memory import (
    CommandSummary,
    WorkingMemory,
)


def test_working_memory_records_read_and_search_files_without_duplicates():
    memory = WorkingMemory()

    memory.record_tool_result(
        tool_name="read_file",
        arguments={"path": "src/a.py"},
        result={"ok": True, "path": "src/a.py"},
        step=1,
    )

    memory.record_tool_result(
        tool_name="search_text",
        arguments={"query": "foo"},
        result={
            "ok": True,
            "matches": [
                {"path": "src/a.py", "line": 1, "text": "foo"},
                {"path": "src/b.py", "line": 2, "text": "foo"},
            ],
        },
        step=2,
    )

    assert memory.inspected_files == [
        "src/a.py",
        "src/b.py",
    ]


def test_working_memory_records_modified_files():
    memory = WorkingMemory()

    memory.record_tool_result(
        tool_name="write_file",
        arguments={"path": "main.py"},
        result={"ok": True, "path": "main.py"},
        step=1,
    )

    memory.record_tool_result(
        tool_name="edit_file",
        arguments={"path": "main.py"},
        result={"ok": True, "path": "main.py"},
        step=2,
    )

    assert memory.modified_files == ["main.py"]


def test_working_memory_bounds_recent_commands():
    memory = WorkingMemory()

    for index in range(7):
        memory.record_tool_result(
            tool_name="run_command",
            arguments={
                "argv": ["python", f"script_{index}.py"],
                "purpose": "run",
            },
            result={"ok": True, "returncode": 0},
            step=index + 1,
        )

    assert len(memory.recent_commands) == memory.MAX_RECENT_COMMANDS
    assert memory.recent_commands[0].argv == [
        "python",
        "script_2.py",
    ]
    assert memory.recent_commands[-1].argv == [
        "python",
        "script_6.py",
    ]


def test_working_memory_tracks_failed_command_and_error():
    memory = WorkingMemory()

    memory.record_tool_result(
        tool_name="run_command",
        arguments={
            "argv": ["python", "bad.py"],
            "purpose": "test",
        },
        result={
            "ok": False,
            "returncode": 1,
            "stderr": "AssertionError: boom",
        },
        step=3,
    )

    assert memory.last_failed_command is not None
    assert memory.last_failed_command.argv == ["python", "bad.py"]
    assert memory.last_error == "AssertionError: boom"
    assert memory.last_validation is not None
    assert memory.last_validation.ok is False
    assert memory.validation_status == "failed"


def test_working_memory_revision_status_passed_then_stale():
    memory = WorkingMemory()

    memory.sync_revisions(
        current_revision="revision-a",
        validated_revision="revision-a",
    )

    assert memory.validation_status == "passed"

    memory.sync_revisions(
        current_revision="revision-b",
        validated_revision="revision-a",
    )

    assert memory.validation_status == "stale"


def test_working_memory_restore_round_trip_fields():
    memory = WorkingMemory()

    memory.restore(
        {
            "inspected_files": ["a.py"],
            "modified_files": ["b.py"],
            "recent_commands": [
                {
                    "argv": ["python", "b.py"],
                    "purpose": "test",
                    "ok": True,
                    "returncode": 0,
                    "step": 4,
                }
            ],
            "last_failed_command": None,
            "last_error": None,
            "current_revision": "revision-a",
            "validated_revision": "revision-a",
            "last_validation": {
                "argv": ["python", "b.py"],
                "purpose": "test",
                "ok": True,
                "returncode": 0,
                "step": 4,
            },
        }
    )

    assert memory.inspected_files == ["a.py"]
    assert memory.modified_files == ["b.py"]
    assert memory.validation_status == "passed"
    assert memory.last_validation == CommandSummary(
        argv=["python", "b.py"],
        purpose="test",
        ok=True,
        returncode=0,
        step=4,
    )


def test_working_memory_context_message_is_compact_runtime_fact_summary():
    memory = WorkingMemory(
        inspected_files=["src/a.py"],
        modified_files=["src/a.py", "tests/test_a.py"],
        current_revision="abcdef1234567890",
        validated_revision="abcdef1234567890",
        last_validation=CommandSummary(
            argv=["python", "-m", "pytest", "-q"],
            purpose="test",
            ok=True,
            returncode=0,
            step=5,
        ),
    )

    message = memory.to_context_message()

    assert message["role"] == "system"
    assert "[Runtime working memory]" in message["content"]
    assert "src/a.py" in message["content"]
    assert "tests/test_a.py" in message["content"]
    assert "Validation status: passed" in message["content"]
    assert "abcdef123456" in message["content"]
    assert "python -m pytest -q" in message["content"]

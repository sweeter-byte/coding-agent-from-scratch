import json
from pathlib import Path
from types import SimpleNamespace

from agent.agent import CodingAgent
from storage.session_store import SessionStore
from storage.trace_logger import TraceLogger as RealTraceLogger


def tool_call(call_id: str, name: str, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )


def response(content: str = "", calls=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=calls or [],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=None,
    )


class FakeLLMClient:
    """Deterministic fake model used to test the whole agent loop."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create_completion(self, messages, tools):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
            }
        )
        if not self.responses:
            raise AssertionError("Fake LLM ran out of responses")
        return self.responses.pop(0)


def test_agent_write_guard_validate_finish_flow(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    fake_llm = FakeLLMClient(
        [
            # Step 1: create source code.
            response(
                calls=[
                    tool_call(
                        "call-write",
                        "write_file",
                        {
                            "path": "hello.py",
                            "content": "print('hello')\n",
                        },
                    )
                ]
            ),
            # Step 2: model tries to finish too early.
            response(content="Done."),
            # Step 3: runtime feedback should cause validation.
            response(
                calls=[
                    tool_call(
                        "call-test",
                        "run_command",
                        {
                            "argv": ["python", "hello.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            # Step 4: now completion is accepted.
            response(content="Task completed and validated."),
        ]
    )

    trace_dir = tmp_path / "traces"

    def temp_trace_logger(*, run_id):
        return RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        )

    # CodingAgent constructs TraceLogger inside run(), so redirect it
    # to the pytest temporary directory.
    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        temp_trace_logger,
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run("Create a Python program that prints hello")

    assert result == "Task completed and validated."
    assert (agent_config.workspace / "hello.py").read_text(
        encoding="utf-8"
    ) == "print('hello')\n"

    assert agent.state.step == 4
    assert agent.state.write_version == 1
    assert agent.state.validated_version == 1
    assert agent.state.latest_version_validated is True
    assert agent.state.total_tool_calls == 2

    # The third model call must see the runtime guard feedback generated
    # after the model attempted to finish before validation.
    third_context = fake_llm.calls[2]["messages"]
    assert any(
        message.get("role") == "user"
        and "latest source-code version has not passed" in message.get(
            "content", ""
        )
        for message in third_context
    )

    stored = agent.session_store.load(agent.session_id)
    assert stored["metadata"]["status"] == "completed"
    assert stored["state"]["write_version"] == 1
    assert stored["state"]["validated_version"] == 1

    trace_path = trace_dir / f"run_{agent.session_id}.jsonl"
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    events = [record["event"] for record in records]

    assert "agent_start" in events
    assert "runtime_feedback" in events
    assert "tool_call" in events
    assert "tool_result" in events
    assert "agent_finish" in events


def test_agent_recovers_from_invalid_tool_json(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    invalid_call = SimpleNamespace(
        id="bad-call",
        function=SimpleNamespace(
            name="write_file",
            arguments="{bad json",
        ),
    )

    fake_llm = FakeLLMClient(
        [
            response(calls=[invalid_call]),
            response(
                calls=[
                    tool_call(
                        "good-write",
                        "write_file",
                        {
                            "path": "ok.py",
                            "content": "print('ok')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "good-test",
                        "run_command",
                        {
                            "argv": ["python", "ok.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Recovered successfully."),
        ]
    )

    trace_dir = tmp_path / "traces"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run("Create and test ok.py")

    assert result == "Recovered successfully."
    assert agent.state.latest_version_validated is True
    # bad tool call + good write + good test
    assert agent.state.total_tool_calls == 3
    # A later successful tool resets the consecutive error counter.
    assert agent.state.consecutive_errors == 0

    history = agent.history.get_messages()
    bad_result = next(
        message
        for message in history
        if message.get("role") == "tool"
        and message.get("tool_call_id") == "bad-call"
    )
    parsed_bad_result = json.loads(bad_result["content"])
    assert parsed_bad_result["ok"] is False
    assert "Invalid JSON arguments" in parsed_bad_result["error"]


def test_agent_can_resume_failed_session_and_continue_same_runtime(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    from dataclasses import replace

    trace_dir = tmp_path / "traces"
    session_dir = tmp_path / "sessions"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    first_config = replace(
        agent_config,
        max_steps=2,
    )

    first_agent = CodingAgent(
        config=first_config
    )
    first_agent.session_store = SessionStore(
        session_dir
    )
    first_agent.llm_client = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "write-1",
                        "write_file",
                        {
                            "path": "resume_demo.py",
                            "content": "print('resume ok')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "bad-test",
                        "run_command",
                        {
                            "argv": ["python", "missing.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
        ]
    )

    import pytest

    with pytest.raises(RuntimeError, match="maximum number of steps"):
        first_agent.run("Create and test resume_demo.py")

    session_id = first_agent.session_id
    assert session_id is not None

    failed_snapshot = first_agent.session_store.load(session_id)
    assert failed_snapshot["metadata"]["status"] == "failed"
    assert failed_snapshot["state"]["step"] == 2
    assert failed_snapshot["state"]["write_version"] == 1
    assert failed_snapshot["state"]["validated_version"] == -1

    resumed_config = replace(
        agent_config,
        max_steps=5,
    )

    resumed_agent = CodingAgent(
        config=resumed_config
    )
    resumed_agent.session_store = SessionStore(
        session_dir
    )

    resumed_llm = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "good-test",
                        "run_command",
                        {
                            "argv": ["python", "resume_demo.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(
                content="Resumed task completed and validated."
            ),
        ]
    )
    resumed_agent.llm_client = resumed_llm

    result = resumed_agent.resume(
        session_id
    )

    assert result == "Resumed task completed and validated."
    assert resumed_agent.session_id == session_id
    assert resumed_agent.current_task == "Create and test resume_demo.py"
    assert resumed_agent.state.step == 4
    assert resumed_agent.state.write_version == 1
    assert resumed_agent.state.validated_version == 1
    assert resumed_agent.state.latest_version_validated is True

    # The first model call after resume must already contain the old
    # conversation, including the previous failed validation result.
    resumed_context = resumed_llm.calls[0]["messages"]
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "bad-test"
        for message in resumed_context
    )

    resumed_memory = next(
        message
        for message in resumed_context
        if message.get("role") == "system"
        and message.get("content", "").startswith(
            "[Runtime working memory]"
        )
    )
    assert "resume_demo.py" in resumed_memory["content"]
    assert "python missing.py" in resumed_memory["content"]
    assert "Validation status: not_validated" in resumed_memory["content"]

    completed_snapshot = resumed_agent.session_store.load(session_id)
    assert completed_snapshot["metadata"]["status"] == "completed"
    assert completed_snapshot["metadata"]["error"] is None
    assert completed_snapshot["state"]["step"] == 4

    trace_path = trace_dir / f"run_{session_id}.jsonl"
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    events = [record["event"] for record in records]
    assert "session_resume" in events
    assert "agent_finish" in events


def test_agent_resume_rejects_completed_session(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    trace_dir = tmp_path / "traces"
    session_dir = tmp_path / "sessions"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    store = SessionStore(session_dir)
    session_id = store.create_session(
        metadata={
            "task": "done task",
            "model": agent_config.model,
            "workspace": str(agent_config.workspace),
            "status": "completed",
        }
    )
    store.save(
        session_id,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "done task"},
        ],
        state={
            "step": 2,
            "write_version": 1,
            "validated_version": 1,
            "total_tool_calls": 2,
            "consecutive_errors": 0,
            "last_tool_name": "run_command",
            "last_error": None,
        },
    )

    agent = CodingAgent(config=agent_config)
    agent.session_store = store

    import pytest

    with pytest.raises(ValueError, match="Completed sessions"):
        agent.resume(session_id)


def test_agent_resume_rejects_workspace_mismatch(
    tmp_path: Path,
    agent_config,
):
    from dataclasses import replace
    import pytest

    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session(
        metadata={
            "task": "demo",
            "workspace": str(agent_config.workspace),
            "status": "failed",
        }
    )
    store.save(
        session_id,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "demo"},
        ],
        state={"step": 1},
    )

    other_config = replace(
        agent_config,
        workspace=tmp_path / "another-workspace",
    )

    agent = CodingAgent(config=other_config)
    agent.session_store = store

    with pytest.raises(ValueError, match="workspace does not match"):
        agent.resume(session_id)


def test_agent_resume_requires_larger_max_steps_when_limit_reached(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    import pytest

    trace_dir = tmp_path / "traces"
    session_dir = tmp_path / "sessions"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    store = SessionStore(session_dir)
    session_id = store.create_session(
        metadata={
            "task": "demo",
            "workspace": str(agent_config.workspace),
            "status": "failed",
        }
    )
    store.save(
        session_id,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "demo"},
        ],
        state={
            "step": agent_config.max_steps,
            "write_version": 1,
            "validated_version": -1,
            "total_tool_calls": 1,
            "consecutive_errors": 0,
            "last_tool_name": "write_file",
            "last_error": None,
        },
    )

    agent = CodingAgent(config=agent_config)
    agent.session_store = store

    with pytest.raises(RuntimeError, match="larger --max-steps"):
        agent.resume(session_id)

    # A rejected resume must not rewrite the persisted status to running.
    snapshot = store.load(session_id)
    assert snapshot["metadata"]["status"] == "failed"


def test_agent_search_read_edit_validate_finish_flow(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    """
    Exercise the intended existing-project workflow:

        search_text -> read_file -> edit_file -> run_command -> finish

    edit_file must count as a source change, so the runtime may only
    accept completion after the edited version is validated.
    """

    source = agent_config.workspace / "app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "def greet():\n"
        "    return 'old'\n"
        "\n"
        "print(greet())\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "call-search",
                        "search_text",
                        {
                            "query": "return 'old'",
                            "file_pattern": "*.py",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "call-read",
                        "read_file",
                        {
                            "path": "app.py",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "call-edit",
                        "edit_file",
                        {
                            "path": "app.py",
                            "old_text": "    return 'old'",
                            "new_text": "    return 'new'",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "call-test",
                        "run_command",
                        {
                            "argv": ["python", "app.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Updated and validated app.py."),
        ]
    )

    trace_dir = tmp_path / "traces"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run(
        "Change the existing app.py greeting from old to new and test it"
    )

    assert result == "Updated and validated app.py."
    assert source.read_text(encoding="utf-8") == (
        "def greet():\n"
        "    return 'new'\n"
        "\n"
        "print(greet())\n"
    )

    assert agent.state.step == 5
    assert agent.state.total_tool_calls == 4
    assert agent.state.write_version == 1
    assert agent.state.validated_version == 1
    assert agent.state.latest_version_validated is True

    tool_names = set(agent.tool_registry.list_tools())
    assert "search_text" in tool_names
    assert "edit_file" in tool_names

    history = agent.history.get_messages()
    search_result_message = next(
        message
        for message in history
        if message.get("role") == "tool"
        and message.get("tool_call_id") == "call-search"
    )
    search_result = json.loads(search_result_message["content"])
    assert search_result["ok"] is True
    assert search_result["matches"][0]["path"] == "app.py"


def test_agent_edit_pytest_fail_fix_pytest_pass_finish_flow(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    """
    Exercise a realistic recovery loop in a project subdirectory:

        read -> edit -> pytest fails -> edit -> pytest passes -> finish

    The first failing pytest run must not validate the edited source.
    The second successful pytest run validates the newest edit version.
    """

    project_dir = agent_config.workspace / "project"
    project_dir.mkdir(parents=True, exist_ok=True)

    source = project_dir / "app.py"
    source.write_text(
        "def greeting():\n"
        "    return 'old'\n",
        encoding="utf-8",
    )

    (project_dir / "test_app.py").write_text(
        "from app import greeting\n"
        "\n"
        "def test_greeting():\n"
        "    assert greeting() == 'new'\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "read-app",
                        "read_file",
                        {"path": "project/app.py"},
                    )
                ]
            ),
            # First edit is intentionally wrong so pytest fails.
            response(
                calls=[
                    tool_call(
                        "bad-edit",
                        "edit_file",
                        {
                            "path": "project/app.py",
                            "old_text": "    return 'old'",
                            "new_text": "    return 'broken'",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "failing-pytest",
                        "run_command",
                        {
                            "argv": ["python", "-m", "pytest", "-q"],
                            "purpose": "test",
                            "cwd": "project",
                        },
                    )
                ]
            ),
            # Recover from the test output with a targeted second edit.
            response(
                calls=[
                    tool_call(
                        "good-edit",
                        "edit_file",
                        {
                            "path": "project/app.py",
                            "old_text": "    return 'broken'",
                            "new_text": "    return 'new'",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "passing-pytest",
                        "run_command",
                        {
                            "argv": ["python", "-m", "pytest", "-q"],
                            "purpose": "test",
                            "cwd": "project",
                        },
                    )
                ]
            ),
            response(content="Fixed the code and all project tests pass."),
        ]
    )

    trace_dir = tmp_path / "traces"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run(
        "Update project/app.py so the existing pytest suite passes"
    )

    assert result == "Fixed the code and all project tests pass."
    assert source.read_text(encoding="utf-8") == (
        "def greeting():\n"
        "    return 'new'\n"
    )

    assert agent.state.write_version == 2
    assert agent.state.validated_version == 2
    assert agent.state.latest_version_validated is True
    assert agent.state.total_tool_calls == 5
    assert agent.state.consecutive_errors == 0

    history = agent.history.get_messages()

    failed_message = next(
        message
        for message in history
        if message.get("role") == "tool"
        and message.get("tool_call_id") == "failing-pytest"
    )
    failed_result = json.loads(failed_message["content"])
    assert failed_result["ok"] is False
    assert failed_result["returncode"] == 1
    assert failed_result["cwd"] == "project"

    passed_message = next(
        message
        for message in history
        if message.get("role") == "tool"
        and message.get("tool_call_id") == "passing-pytest"
    )
    passed_result = json.loads(passed_message["content"])
    assert passed_result["ok"] is True
    assert passed_result["returncode"] == 0
    assert passed_result["cwd"] == "project"


def test_agent_rejects_finish_after_external_workspace_change(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    source_path = agent_config.workspace / "revision_demo.py"

    class MutatingFakeLLMClient(FakeLLMClient):
        def create_completion(self, messages, tools):
            # Before the third model response attempts to finish, emulate
            # an external editor changing the file behind the agent's back.
            if len(self.calls) == 2:
                source_path.write_text(
                    "print('externally changed')\n",
                    encoding="utf-8",
                )

            return super().create_completion(messages, tools)

    fake_llm = MutatingFakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "write-revision",
                        "write_file",
                        {
                            "path": "revision_demo.py",
                            "content": "print('original')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "test-original",
                        "run_command",
                        {
                            "argv": ["python", "revision_demo.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Finished after first validation."),
            response(
                calls=[
                    tool_call(
                        "test-changed",
                        "run_command",
                        {
                            "argv": ["python", "revision_demo.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Finished after revalidation."),
        ]
    )

    trace_dir = tmp_path / "traces"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run(
        "Create and validate revision_demo.py"
    )

    assert result == "Finished after revalidation."
    assert agent.state.step == 5
    assert agent.state.latest_version_validated is True
    assert len(agent.state.validation_records) == 2
    assert (
        agent.state.validation_records[0].revision
        != agent.state.validation_records[1].revision
    )

    fourth_context = fake_llm.calls[3]["messages"]
    assert any(
        message.get("role") == "user"
        and "workspace changed after the last successful validation"
        in message.get("content", "").lower()
        for message in fourth_context
    )

    stored = agent.session_store.load(agent.session_id)
    assert stored["metadata"]["status"] == "completed"
    assert stored["state"]["current_revision"] == (
        stored["state"]["validated_revision"]
    )
    assert len(stored["state"]["validation_records"]) == 2



def test_agent_does_not_validate_revision_created_during_command_execution(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    fake_llm = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "write-app",
                        "write_file",
                        {
                            "path": "app.py",
                            "content": "print('original')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "write-mutator",
                        "write_file",
                        {
                            "path": "mutate.py",
                            "content": (
                                "from pathlib import Path\n"
                                "Path('app.py').write_text(\"print('mutated')\\n\", encoding='utf-8')\n"
                            ),
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "run-mutator",
                        "run_command",
                        {
                            "argv": ["python", "mutate.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Finish after mutating run."),
            response(
                calls=[
                    tool_call(
                        "run-final",
                        "run_command",
                        {
                            "argv": ["python", "app.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Finish after stable validation."),
        ]
    )

    trace_dir = tmp_path / "traces"
    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=agent_config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run("Create app.py and validate its final contents")

    assert result == "Finish after stable validation."
    assert agent.state.latest_version_validated is True
    assert len(agent.state.validation_records) == 1

    mutator_result_message = next(
        message
        for message in fake_llm.calls[3]["messages"]
        if message.get("role") == "tool"
        and message.get("tool_call_id") == "run-mutator"
    )
    mutator_result = json.loads(mutator_result_message["content"])
    assert mutator_result["ok"] is True
    assert mutator_result["validation_eligible"] is True
    assert mutator_result["workspace_revision_stable"] is False
    assert "did not create validation evidence" in mutator_result["validation_note"]

    guard_context = fake_llm.calls[4]["messages"]
    assert any(
        message.get("role") == "user"
        and "has not passed successful runtime validation"
        in message.get("content", "").lower()
        for message in guard_context
    )


def test_resume_detects_workspace_change_and_requires_revalidation(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    from dataclasses import replace
    import pytest

    trace_dir = tmp_path / "traces"
    session_dir = tmp_path / "sessions"

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=trace_dir,
            run_id=run_id,
        ),
    )

    first_agent = CodingAgent(
        config=replace(
            agent_config,
            max_steps=2,
        )
    )
    first_agent.session_store = SessionStore(session_dir)
    first_agent.llm_client = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "resume-write-revision",
                        "write_file",
                        {
                            "path": "resume_revision.py",
                            "content": "print('v1')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "resume-test-revision",
                        "run_command",
                        {
                            "argv": ["python", "resume_revision.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
        ]
    )

    with pytest.raises(RuntimeError, match="maximum number of steps"):
        first_agent.run("Create and test resume_revision.py")

    session_id = first_agent.session_id
    assert session_id is not None
    assert first_agent.state.latest_version_validated is True

    source = agent_config.workspace / "resume_revision.py"
    source.write_text("print('v2 external')\n", encoding="utf-8")

    resumed_llm = FakeLLMClient(
        [
            response(content="Finish using old validation."),
            response(
                calls=[
                    tool_call(
                        "resume-retest-revision",
                        "run_command",
                        {
                            "argv": ["python", "resume_revision.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Finish after fresh validation."),
        ]
    )

    resumed_agent = CodingAgent(
        config=replace(
            agent_config,
            max_steps=5,
        )
    )
    resumed_agent.session_store = SessionStore(session_dir)
    resumed_agent.llm_client = resumed_llm

    result = resumed_agent.resume(session_id)

    assert result == "Finish after fresh validation."
    assert resumed_agent.state.step == 5
    assert resumed_agent.state.latest_version_validated is True
    assert len(resumed_agent.state.validation_records) == 2

    first_resume_context = resumed_llm.calls[0]["messages"]
    assert any(
        message.get("role") == "user"
        and "workspace contents changed since this session"
        in message.get("content", "").lower()
        for message in first_resume_context
    )


def test_agent_injects_structured_working_memory_into_each_model_context(
    monkeypatch,
    tmp_path: Path,
    agent_config,
):
    from dataclasses import replace

    config = replace(
        agent_config,
        max_context_messages=2,
    )

    fake_llm = FakeLLMClient(
        [
            response(
                calls=[
                    tool_call(
                        "write-memory",
                        "write_file",
                        {
                            "path": "memory_demo.py",
                            "content": "print('memory ok')\n",
                        },
                    )
                ]
            ),
            response(
                calls=[
                    tool_call(
                        "test-memory",
                        "run_command",
                        {
                            "argv": ["python", "memory_demo.py"],
                            "purpose": "run",
                        },
                    )
                ]
            ),
            response(content="Working memory task completed."),
        ]
    )

    monkeypatch.setattr(
        "agent.agent.TraceLogger",
        lambda *, run_id: RealTraceLogger(
            directory=tmp_path / "traces",
            run_id=run_id,
        ),
    )

    agent = CodingAgent(config=config)
    agent.llm_client = fake_llm
    agent.session_store = SessionStore(tmp_path / "sessions")

    result = agent.run("Create and test memory_demo.py")

    assert result == "Working memory task completed."

    second_context = fake_llm.calls[1]["messages"]
    second_memory = next(
        message
        for message in second_context
        if message.get("role") == "system"
        and message.get("content", "").startswith("[Runtime working memory]")
    )

    assert "memory_demo.py" in second_memory["content"]
    assert "Validation status: not_validated" in second_memory["content"]

    final_context = fake_llm.calls[2]["messages"]
    final_memory = next(
        message
        for message in final_context
        if message.get("role") == "system"
        and message.get("content", "").startswith("[Runtime working memory]")
    )

    assert "Validation status: passed" in final_memory["content"]
    assert "python memory_demo.py" in final_memory["content"]

    stored = agent.session_store.load(agent.session_id)
    assert stored["state"]["working_memory"]["modified_files"] == [
        "memory_demo.py"
    ]

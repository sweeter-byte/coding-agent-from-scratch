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
                            "purpose": "test",
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
                            "purpose": "test",
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
                            "purpose": "test",
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
                            "purpose": "test",
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

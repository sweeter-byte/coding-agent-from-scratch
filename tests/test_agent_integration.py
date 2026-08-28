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

from pathlib import Path

import pytest

from agent.history import ConversationHistory
from agent.state import AgentState
from storage.session_store import SessionStore


def test_create_save_and_load_session(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session(
        metadata={"task": "demo", "status": "running"}
    )

    store.save(
        session_id,
        messages=[{"role": "user", "content": "hello"}],
        metadata={"status": "completed"},
        state={"step": 2},
    )

    data = store.load(session_id)

    assert data["session_id"] == session_id
    assert data["metadata"]["task"] == "demo"
    assert data["metadata"]["status"] == "completed"
    assert data["state"]["step"] == 2
    assert data["messages"] == [
        {"role": "user", "content": "hello"}
    ]
    assert data["created_at"]
    assert data["updated_at"]


def test_save_history_serializes_agent_state(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session()

    history = ConversationHistory()
    history.reset("system", "task")
    state = AgentState(step=3, write_version=1, validated_version=1)

    store.save_history(
        session_id,
        history,
        metadata={"status": "completed"},
        state=state,
    )

    data = store.load(session_id)

    assert data["messages"] == history.get_messages()
    assert data["state"]["step"] == 3
    assert data["state"]["write_version"] == 1
    assert data["state"]["validated_version"] == 1


def test_restore_history(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "answer"},
    ]
    store.save(session_id, messages=messages)

    history = ConversationHistory()
    session = store.restore_history(session_id, history)

    assert history.get_messages() == messages
    assert session["session_id"] == session_id


def test_list_sessions_returns_lightweight_metadata(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session(metadata={"task": "demo"})
    store.save(
        session_id,
        messages=[{"role": "user", "content": "hello"}],
    )

    sessions = store.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["message_count"] == 1
    assert sessions[0]["metadata"]["task"] == "demo"


def test_delete_session(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session()

    assert store.exists(session_id) is True
    assert store.delete(session_id) is True
    assert store.exists(session_id) is False
    assert store.delete(session_id) is False


def test_invalid_session_id_is_rejected(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")

    with pytest.raises(ValueError, match="Invalid session_id"):
        store.load("../escape")


def test_atomic_save_leaves_no_temporary_files(tmp_path: Path):
    directory = tmp_path / "sessions"
    store = SessionStore(directory)
    session_id = store.create_session()

    store.save(
        session_id,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert list(directory.glob("*.tmp-*")) == []

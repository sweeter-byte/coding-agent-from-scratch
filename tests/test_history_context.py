from agent.context import ContextManager
from agent.history import ConversationHistory


def assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


def test_history_reset_and_copy_isolation():
    history = ConversationHistory()
    history.reset("system", "task")

    messages = history.get_messages()
    messages[0]["content"] = "mutated"

    fresh = history.get_messages()
    assert fresh == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]


def test_history_rejects_invalid_role_on_restore():
    history = ConversationHistory()

    try:
        history.restore([{"role": "invalid", "content": "x"}])
    except ValueError as exc:
        assert "Invalid message role" in str(exc)
    else:
        raise AssertionError("Expected invalid role to be rejected")


def test_context_keeps_system_original_task_and_recent_tail():
    history = ConversationHistory()
    history.reset("system", "original task")
    history.add_assistant_message(assistant("old-1"))
    history.add_user_message("old-2")
    history.add_assistant_message(assistant("recent-1"))
    history.add_user_message("recent-2")

    context = ContextManager(max_context_messages=3).build(history)

    assert context[0]["role"] == "system"
    assert context[0]["content"] == "system"
    assert context[1]["role"] == "user"
    assert context[1]["content"] == "original task"
    assert [message["content"] for message in context[2:]] == [
        "recent-1",
        "recent-2",
    ]


def test_context_never_starts_retained_tail_with_orphan_tool_message():
    history = ConversationHistory()
    history.reset("system", "task")
    history.add_assistant_message(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": "{}",
                    },
                }
            ],
        }
    )
    history.add_tool_result("call-1", '{"ok": true}')
    history.add_assistant_message(assistant("latest"))

    context = ContextManager(max_context_messages=3).build(history)

    assert [message["role"] for message in context] == [
        "system",
        "user",
        "assistant",
    ]
    assert context[-1]["content"] == "latest"


def test_context_fallback_without_system_message():
    history = ConversationHistory()
    history.restore(
        [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]
    )

    context = ContextManager(max_context_messages=2).build(history)

    assert [message["content"] for message in context] == [
        "two",
        "three",
    ]


def test_context_injects_runtime_working_memory_without_consuming_tail_budget():
    from agent.working_memory import WorkingMemory

    history = ConversationHistory()
    history.reset("system", "original task")
    history.add_assistant_message(
        {"role": "assistant", "content": "old-1"}
    )
    history.add_user_message("old-2")
    history.add_assistant_message(
        {"role": "assistant", "content": "recent-1"}
    )
    history.add_user_message("recent-2")

    memory = WorkingMemory(
        inspected_files=["src/main.py"],
        modified_files=["src/main.py"],
        current_revision="revision-a",
    )

    context = ContextManager(
        max_context_messages=3
    ).build(
        history,
        working_memory=memory,
    )

    assert context[0] == {
        "role": "system",
        "content": "system",
    }
    assert context[1]["role"] == "system"
    assert "[Runtime working memory]" in context[1]["content"]
    assert "src/main.py" in context[1]["content"]
    assert context[2] == {
        "role": "user",
        "content": "original task",
    }
    assert [
        message["content"]
        for message in context[3:]
    ] == ["recent-1", "recent-2"]


def test_context_without_working_memory_keeps_previous_layout():
    history = ConversationHistory()
    history.reset("system", "task")
    history.add_assistant_message(
        {"role": "assistant", "content": "answer"}
    )

    context = ContextManager(
        max_context_messages=4
    ).build(history)

    assert context == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "answer"},
    ]

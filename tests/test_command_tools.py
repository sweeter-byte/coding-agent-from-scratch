import json
from pathlib import Path

from tools.command_tools import CommandTools


def decode(result: str) -> dict:
    return json.loads(result)


def write_script(root: Path, name: str, source: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(source, encoding="utf-8")


def test_run_python_script_success(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "hello.py", "print('hello')\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["stdout"].strip() == "hello"


def test_nonzero_exit_is_reported_as_failure(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "fail.py", "raise SystemExit(3)\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "fail.py"],
            purpose="test",
        )
    )

    assert result["ok"] is False
    assert result["returncode"] == 3


def test_rejects_inline_python_execution(tmp_path: Path):
    tools = CommandTools(tmp_path / "workspace")

    result = decode(
        tools.run_command(
            ["python", "-c", "print('unsafe mode')"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "Inline/module Python execution" in result["error"]


def test_rejects_invalid_purpose(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "hello.py", "print('hello')\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="delete",
        )
    )

    assert result["ok"] is False
    assert "purpose must be one of" in result["error"]


def test_rejects_script_outside_workspace(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "../outside.py"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]


def test_command_timeout(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(
        root,
        "slow.py",
        "import time\ntime.sleep(2)\nprint('done')\n",
    )
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "slow.py"],
            purpose="test",
            timeout_seconds=1,
        )
    )

    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_child_process_does_not_receive_api_key(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    write_script(
        root,
        "env_check.py",
        (
            "import os\n"
            "print(os.getenv('QWEN_API_KEY', 'MISSING'))\n"
        ),
    )
    monkeypatch.setenv("QWEN_API_KEY", "super-secret")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "env_check.py"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["stdout"].strip() == "MISSING"

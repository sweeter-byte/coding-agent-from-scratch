import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

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
            purpose="run",
        )
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["cwd"] == "."
    assert result["stdout"].strip() == "hello"
    assert result["purpose"] == "run"
    assert result["validation_eligible"] is True


def test_run_python_script_from_workspace_subdirectory(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root / "backend", "hello.py", "print('backend')\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="run",
            cwd="backend",
        )
    )

    assert result["ok"] is True
    assert result["cwd"] == "backend"
    assert result["stdout"].strip() == "backend"


def test_rejects_cwd_escape(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="run",
            cwd="../outside",
        )
    )

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]


def test_rejects_absolute_cwd(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="run",
            cwd=str(tmp_path),
        )
    )

    assert result["ok"] is False
    assert "Absolute paths are not allowed" in result["error"]


def test_nonzero_exit_is_reported_as_failure(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "fail.py", "raise SystemExit(3)\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "fail.py"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert result["returncode"] == 3
    assert result["timed_out"] is False


def test_rejects_inline_python_execution(tmp_path: Path):
    tools = CommandTools(tmp_path / "workspace")

    result = decode(
        tools.run_command(
            ["python", "-c", "print('unsafe mode')"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "Inline Python execution" in result["error"]


def test_rejects_arbitrary_python_module_execution(tmp_path: Path):
    tools = CommandTools(tmp_path / "workspace")

    result = decode(
        tools.run_command(
            ["python", "-m", "http.server"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "Only 'python -m pytest'" in result["error"]


def test_python_module_pytest_is_allowed(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "test_sample.py").write_text(
        "def test_ok():\n"
        "    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "-m", "pytest", "test_sample.py", "-q"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "1 passed" in result["stdout"]


def test_direct_pytest_is_allowed_when_available(tmp_path: Path):
    if shutil.which("pytest") is None:
        pytest.skip("pytest executable is not available on PATH")

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "test_sample.py").write_text(
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["pytest", "test_sample.py", "-q"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["returncode"] == 0


def test_pytest_failure_returns_structured_nonzero_result(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "test_fail.py").write_text(
        "def test_fail():\n"
        "    assert False\n",
        encoding="utf-8",
    )
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "-m", "pytest", "test_fail.py", "-q"],
            purpose="test",
        )
    )

    assert result["ok"] is False
    assert result["returncode"] == 1
    assert result["timed_out"] is False
    assert "FAILED" in result["stdout"]


def test_pytest_target_cannot_escape_workspace(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside_test.py"
    outside.write_text("def test_ok(): assert True\n", encoding="utf-8")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "-m", "pytest", "../outside_test.py", "-q"],
            purpose="test",
        )
    )

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]


def test_rejects_unsupported_pytest_option(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "-m", "pytest", "--basetemp=/tmp/agent-tests"],
            purpose="test",
        )
    )

    assert result["ok"] is False
    assert "Unsupported pytest option" in result["error"]



def test_rejects_purpose_that_does_not_match_command_type(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "hello.py", "print('hello')\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py"],
            purpose="test",
        )
    )

    assert result["ok"] is False
    assert "purpose does not match the command type" in result["error"]


def test_pytest_collect_only_is_not_validation_eligible(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "-m", "pytest", "--collect-only", "-q"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["validation_eligible"] is False
    assert result["validation_reason"] == "pytest_collect_only"


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


def test_rejects_shell_executable(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["bash", "-c", "echo nope"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "Shell executable is not allowed" in result["error"]


def test_rejects_shell_operator_tokens(tmp_path: Path):
    root = tmp_path / "workspace"
    write_script(root, "hello.py", "print('hello')\n")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "hello.py", "&&", "echo"],
            purpose="run",
        )
    )

    assert result["ok"] is False
    assert "Shell operators are not supported" in result["error"]


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
            purpose="run",
            timeout_seconds=1,
        )
    )

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["returncode"] is None
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
            "for key in ('QWEN_API_KEY', 'GITHUB_TOKEN', 'HF_TOKEN', 'AWS_ACCESS_KEY_ID'):\n"
            "    print(f'{key}={os.getenv(key, \"MISSING\")}')\n"
        ),
    )
    monkeypatch.setenv("QWEN_API_KEY", "super-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    tools = CommandTools(root)

    result = decode(
        tools.run_command(
            ["python", "env_check.py"],
            purpose="run",
        )
    )

    assert result["ok"] is True
    lines = result["stdout"].strip().splitlines()
    assert lines == [
        "QWEN_API_KEY=MISSING",
        "GITHUB_TOKEN=MISSING",
        "HF_TOKEN=MISSING",
        "AWS_ACCESS_KEY_ID=MISSING",
    ]


def test_cmake_configure_paths_are_kept_inside_workspace(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(demo)\n",
        encoding="utf-8",
    )
    tools = CommandTools(root)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("tools.command_tools.subprocess.run", fake_run)

    result = decode(
        tools.run_command(
            ["cmake", "-S", ".", "-B", "build"],
            purpose="compile",
        )
    )

    assert result["ok"] is True
    assert captured["cwd"] == root.resolve()
    assert captured["command"][2] == str(root.resolve())
    assert captured["command"][4] == str((root / "build").resolve())



def test_ctest_list_only_is_not_validation_eligible(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    build = root / "build"
    build.mkdir(parents=True)
    tools = CommandTools(root)

    monkeypatch.setattr(
        "tools.command_tools.subprocess.run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="listed",
            stderr="",
        ),
    )

    result = decode(
        tools.run_command(
            ["ctest", "--test-dir", "build", "-N"],
            purpose="test",
        )
    )

    assert result["ok"] is True
    assert result["validation_eligible"] is False
    assert result["validation_reason"] == "ctest_list_only"


def test_cmake_build_and_ctest_accept_workspace_build_directory(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    build = root / "build"
    build.mkdir(parents=True)
    tools = CommandTools(root)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("tools.command_tools.subprocess.run", fake_run)

    build_result = decode(
        tools.run_command(
            ["cmake", "--build", "build", "--parallel", "2"],
            purpose="compile",
        )
    )
    test_result = decode(
        tools.run_command(
            ["ctest", "--test-dir", "build", "--output-on-failure"],
            purpose="test",
        )
    )

    assert build_result["ok"] is True
    assert test_result["ok"] is True
    assert calls[0][2] == str(build.resolve())
    assert calls[1][2] == str(build.resolve())

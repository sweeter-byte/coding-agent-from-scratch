from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.acceptance import expand_acceptance_argv, run_acceptance
from evals.loader import discover_cases, load_case
from evals.metrics import collect_trace_metrics
from evals.models import AcceptanceResult, EvalCaseResult, EvalMetrics, EvalRunReport
from evals.report import format_console_summary, write_report
from evals.runner import EvaluationHarness


def _make_case(
    root: Path,
    *,
    name: str = "sample_case",
    task: str = "Create answer.txt containing OK.",
    oracle_source: str | None = None,
    acceptance_argv: list[str] | None = None,
    timeout_seconds: float = 5.0,
) -> Path:
    case_dir = root / name
    project_dir = case_dir / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "input.txt").write_text("seed\n", encoding="utf-8")

    if oracle_source is None:
        oracle_source = (
            "import sys\n"
            "from pathlib import Path\n"
            "workspace = Path(sys.argv[1])\n"
            "assert (workspace / 'answer.txt').read_text(encoding='utf-8').strip() == 'OK'\n"
        )
    (case_dir / "oracle.py").write_text(oracle_source, encoding="utf-8")

    if acceptance_argv is None:
        acceptance_argv = ["{python}", "{case_dir}/oracle.py", "{workspace}"]

    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "name": name,
                "task": task,
                "max_steps": 7,
                "tags": ["test"],
                "acceptance": {
                    "argv": acceptance_argv,
                    "timeout_seconds": timeout_seconds,
                },
            }
        ),
        encoding="utf-8",
    )
    return case_dir


def test_load_case_parses_manifest_and_project(tmp_path: Path):
    case_dir = _make_case(tmp_path)

    case = load_case(case_dir)

    assert case.name == "sample_case"
    assert case.task == "Create answer.txt containing OK."
    assert case.max_steps == 7
    assert case.tags == ("test",)
    assert case.project_dir == (case_dir / "project").resolve()
    assert case.acceptance.timeout_seconds == 5.0


def test_load_case_rejects_invalid_acceptance_argv(tmp_path: Path):
    case_dir = _make_case(tmp_path)
    manifest_path = case_dir / "case.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["acceptance"]["argv"] = "python oracle.py"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="acceptance argv"):
        load_case(case_dir)


def test_discover_cases_is_sorted_and_supports_selection(tmp_path: Path):
    _make_case(tmp_path, name="z_case")
    _make_case(tmp_path, name="a_case")

    all_cases = discover_cases(tmp_path)
    selected = discover_cases(tmp_path, selected_names={"z_case"})

    assert [case.name for case in all_cases] == ["a_case", "z_case"]
    assert [case.name for case in selected] == ["z_case"]

    with pytest.raises(ValueError, match="Unknown evaluation case"):
        discover_cases(tmp_path, selected_names={"missing"})


def test_acceptance_expands_placeholders_and_passes(tmp_path: Path):
    case = load_case(_make_case(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("OK\n", encoding="utf-8")

    argv = expand_acceptance_argv(case, workspace)
    result = run_acceptance(case, workspace)

    assert str(workspace.resolve()) in argv
    assert str(case.case_dir) in argv[1]
    assert result.passed is True
    assert result.returncode == 0
    assert result.timed_out is False


def test_acceptance_strips_secret_environment_variables(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "definitely-not-real")
    oracle = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "assert 'QWEN_API_KEY' not in os.environ\n"
        "workspace = Path(sys.argv[1])\n"
        "assert workspace.is_dir()\n"
    )
    case = load_case(_make_case(tmp_path, oracle_source=oracle))

    result = run_acceptance(case, case.project_dir)

    assert result.passed is True


def test_acceptance_reports_timeout(tmp_path: Path):
    case_dir = _make_case(
        tmp_path,
        acceptance_argv=["{python}", "-c", "import time; time.sleep(1)"],
        timeout_seconds=0.05,
    )
    case = load_case(case_dir)

    result = run_acceptance(case, case.project_dir)

    assert result.passed is False
    assert result.returncode is None
    assert result.timed_out is True


def test_collect_trace_metrics_counts_runtime_events(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    records = [
        {"event": "agent_step", "step": 1},
        {"event": "model_call", "step": 1, "data": {}},
        {"event": "model_response", "step": 1, "data": {"duration_ms": 12.5, "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}},
        {"event": "tool_call", "step": 1, "data": {"tool_name": "run_command", "arguments": {"purpose": "test"}}},
        {"event": "tool_result", "step": 1, "data": {"duration_ms": 3.0}},
        {"event": "workspace_validation", "step": 1, "data": {}},
        {"event": "error", "step": 2, "data": {}},
    ]
    trace.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    metrics = collect_trace_metrics(trace, session_id="session-1")

    assert metrics.steps == 2
    assert metrics.tool_calls == 1
    assert metrics.model_calls == 1
    assert metrics.validation_attempts == 1
    assert metrics.error_events == 1
    assert metrics.model_duration_ms == 12.5
    assert metrics.tool_duration_ms == 3.0
    assert metrics.prompt_tokens == 10
    assert metrics.completion_tokens == 4
    assert metrics.total_tokens == 14
    assert metrics.session_id == "session-1"


class _FakeAgent:
    def __init__(self, workspace: Path, *, should_modify: bool = True, should_raise: bool = False):
        self.workspace = workspace
        self.should_modify = should_modify
        self.should_raise = should_raise
        self.state = SimpleNamespace(step=3, total_tool_calls=4)
        self.session_id = "fake-session"
        self.trace_logger = None

    def run(self, task: str) -> str:
        assert task
        print("fake agent output")
        if self.should_modify:
            (self.workspace / "answer.txt").write_text("OK\n", encoding="utf-8")
        if self.should_raise:
            raise RuntimeError("fake failure")
        return "done"


def test_harness_uses_independent_acceptance_and_writes_reports(tmp_path: Path):
    cases_root = tmp_path / "cases"
    results_root = tmp_path / "results"
    case_dir = _make_case(cases_root)

    harness = EvaluationHarness(
        cases_root=cases_root,
        results_root=results_root,
        agent_factory=lambda workspace, max_steps: _FakeAgent(workspace),
    )
    report = harness.run()

    assert report.total == 1
    assert report.passed == 1
    result = report.results[0]
    assert result.agent_completed is True
    assert result.acceptance.passed is True
    assert result.metrics.steps == 3
    assert result.metrics.tool_calls == 4
    assert not (Path(result.workspace) / "oracle.py").exists()
    assert (case_dir / "oracle.py").exists()

    run_dir = results_root / report.run_id
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "cases" / "sample_case" / "agent_output.txt").is_file()


def test_harness_fails_case_when_agent_finishes_but_acceptance_fails(tmp_path: Path):
    cases_root = tmp_path / "cases"
    _make_case(cases_root)

    harness = EvaluationHarness(
        cases_root=cases_root,
        results_root=tmp_path / "results",
        agent_factory=lambda workspace, max_steps: _FakeAgent(workspace, should_modify=False),
    )
    report = harness.run()

    assert report.passed == 0
    assert report.results[0].agent_completed is True
    assert report.results[0].acceptance.passed is False
    assert report.results[0].passed is False


def test_harness_requires_agent_completion_even_if_workspace_would_pass(tmp_path: Path):
    cases_root = tmp_path / "cases"
    _make_case(cases_root)

    harness = EvaluationHarness(
        cases_root=cases_root,
        results_root=tmp_path / "results",
        agent_factory=lambda workspace, max_steps: _FakeAgent(
            workspace,
            should_modify=True,
            should_raise=True,
        ),
    )
    report = harness.run()

    result = report.results[0]
    assert result.acceptance.passed is True
    assert result.agent_completed is False
    assert "fake failure" in (result.agent_error or "")
    assert result.passed is False


def test_report_writes_json_markdown_and_console_summary(tmp_path: Path):
    acceptance = AcceptanceResult(
        passed=True,
        argv=("python", "oracle.py"),
        returncode=0,
        stdout="",
        stderr="",
        duration_ms=1.0,
    )
    result = EvalCaseResult(
        name="case_a",
        passed=True,
        agent_completed=True,
        agent_result="done",
        agent_error=None,
        acceptance=acceptance,
        metrics=EvalMetrics(steps=2, tool_calls=3, validation_attempts=1),
        workspace="/tmp/workspace",
        duration_ms=1000.0,
    )
    report = EvalRunReport(run_id="run-1", results=[result])

    json_path, markdown_path = write_report(report, tmp_path)
    console = format_console_summary(report)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["success_rate"] == 1.0
    assert "case_a" in markdown_path.read_text(encoding="utf-8")
    assert "Success rate: 1/1" in console

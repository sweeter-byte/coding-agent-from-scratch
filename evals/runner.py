from __future__ import annotations

import argparse
import io
import shutil
import sys

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .acceptance import run_acceptance
from .loader import discover_cases
from .metrics import collect_trace_metrics
from .models import EvalCase, EvalCaseResult, EvalRunReport
from .report import format_console_summary, write_report


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_ROOT = PROJECT_ROOT / "evals" / "cases"
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "evals" / "results"

AgentFactory = Callable[[Path, int], Any]


def _default_agent_factory(workspace: Path, max_steps: int) -> Any:
    """Construct the real CodingAgent lazily so helper modules stay testable."""

    from agent import AgentConfig, CodingAgent

    config = AgentConfig.from_env(
        workspace=str(workspace),
        max_steps=max_steps,
    )
    return CodingAgent(config=config)


class EvaluationHarness:
    """Run reproducible end-to-end coding-agent benchmark cases."""

    def __init__(
        self,
        *,
        cases_root: str | Path = DEFAULT_CASES_ROOT,
        results_root: str | Path = DEFAULT_RESULTS_ROOT,
        agent_factory: AgentFactory | None = None,
        show_agent_output: bool = False,
    ) -> None:
        self.cases_root = Path(cases_root).resolve()
        self.results_root = Path(results_root).resolve()
        self.agent_factory = agent_factory or _default_agent_factory
        self.show_agent_output = show_agent_output

    def run(self, selected_names: set[str] | None = None) -> EvalRunReport:
        cases = discover_cases(self.cases_root, selected_names=selected_names)
        if not cases:
            raise ValueError("No evaluation cases were found.")

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        run_dir = self.results_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        report = EvalRunReport(run_id=run_id)
        for case in cases:
            result = self._run_case(case, run_dir)
            report.results.append(result)
            print(
                f"[{('PASS' if result.passed else 'FAIL')}] "
                f"{case.name} "
                f"steps={result.metrics.steps} "
                f"tools={result.metrics.tool_calls}"
            )

        write_report(report, run_dir)
        print()
        print(format_console_summary(report))
        print(f"\nReport: {run_dir / 'report.md'}")
        return report

    def _run_case(self, case: EvalCase, run_dir: Path) -> EvalCaseResult:
        case_output_dir = run_dir / "cases" / case.name
        workspace = case_output_dir / "workspace"
        case_output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(case.project_dir, workspace)

        agent = self.agent_factory(workspace, case.max_steps)
        output_buffer = io.StringIO()
        agent_completed = False
        agent_result = ""
        agent_error: str | None = None

        started = perf_counter()
        try:
            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                agent_result = str(agent.run(case.task))
            agent_completed = True
        except Exception as exc:  # Evaluation must continue across cases.
            agent_error = f"{type(exc).__name__}: {exc}"

        agent_output = output_buffer.getvalue()
        (case_output_dir / "agent_output.txt").write_text(
            agent_output,
            encoding="utf-8",
        )
        if self.show_agent_output and agent_output:
            print(agent_output, end="" if agent_output.endswith("\n") else "\n")

        acceptance = run_acceptance(case, workspace)
        duration_ms = (perf_counter() - started) * 1000

        state = getattr(agent, "state", None)
        fallback_steps = int(getattr(state, "step", 0) or 0)
        fallback_tool_calls = int(getattr(state, "total_tool_calls", 0) or 0)
        session_id = getattr(agent, "session_id", None)

        trace_logger = getattr(agent, "trace_logger", None)
        trace_path: Path | None = None
        if trace_logger is not None:
            get_log_path = getattr(trace_logger, "get_log_path", None)
            if callable(get_log_path):
                trace_path = Path(get_log_path())
            elif getattr(trace_logger, "path", None) is not None:
                trace_path = Path(trace_logger.path)

        metrics = collect_trace_metrics(
            trace_path,
            fallback_steps=fallback_steps,
            fallback_tool_calls=fallback_tool_calls,
            session_id=session_id,
        )

        return EvalCaseResult(
            name=case.name,
            passed=agent_completed and acceptance.passed,
            agent_completed=agent_completed,
            agent_result=agent_result,
            agent_error=agent_error,
            acceptance=acceptance,
            metrics=metrics,
            workspace=str(workspace),
            duration_ms=duration_ms,
        )


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reproducible end-to-end Coding Agent evaluations."
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Run only the named case. Repeat this option to select multiple cases.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available cases without calling the model.",
    )
    parser.add_argument(
        "--cases-root",
        default=str(DEFAULT_CASES_ROOT),
        help="Directory containing evaluation case folders.",
    )
    parser.add_argument(
        "--results-root",
        default=str(DEFAULT_RESULTS_ROOT),
        help="Directory used for generated evaluation artifacts.",
    )
    parser.add_argument(
        "--show-agent-output",
        action="store_true",
        help="Print captured agent output in addition to saving it per case.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    cases_root = Path(args.cases_root)

    if args.list_cases:
        cases = discover_cases(cases_root)
        for case in cases:
            tags = ", ".join(case.tags) if case.tags else "-"
            print(f"{case.name:<30} tags={tags}")
        return 0

    harness = EvaluationHarness(
        cases_root=cases_root,
        results_root=args.results_root,
        show_agent_output=args.show_agent_output,
    )
    report = harness.run(selected_names=set(args.cases) if args.cases else None)
    return 0 if report.passed == report.total else 1


if __name__ == "__main__":
    sys.exit(main())

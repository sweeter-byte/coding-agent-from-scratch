from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import EvalRunReport


def write_report(report: EvalRunReport, output_dir: str | Path) -> tuple[Path, Path]:
    """Write machine-readable JSON and concise Markdown summaries."""

    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    json_path = directory / "report.json"
    markdown_path = directory / "report.md"

    payload = {
        "run_id": report.run_id,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "success_rate": report.success_rate,
            "average_steps": report.average_steps,
            "average_tool_calls": report.average_tool_calls,
            "average_duration_ms": report.average_duration_ms,
        },
        "results": [asdict(result) for result in report.results],
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Coding Agent Evaluation",
        "",
        f"Run ID: `{report.run_id}`",
        "",
        f"Success: **{report.passed}/{report.total}** ({report.success_rate * 100:.1f}%)",
        f"Average steps: **{report.average_steps:.2f}**",
        f"Average tool calls: **{report.average_tool_calls:.2f}**",
        f"Average duration: **{report.average_duration_ms / 1000:.2f}s**",
        "",
        "| Case | Result | Agent | Steps | Tool calls | Validation attempts | Tokens | Duration |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]

    for result in report.results:
        lines.append(
            "| "
            f"{result.name} | "
            f"{'PASS' if result.passed else 'FAIL'} | "
            f"{'completed' if result.agent_completed else 'error'} | "
            f"{result.metrics.steps} | "
            f"{result.metrics.tool_calls} | "
            f"{result.metrics.validation_attempts} | "
            f"{result.metrics.total_tokens} | "
            f"{result.duration_ms / 1000:.2f}s |"
        )

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def format_console_summary(report: EvalRunReport) -> str:
    """Return a compact human-readable terminal summary."""

    lines = ["Coding Agent Evaluation", "=" * 56]
    for result in report.results:
        lines.append(
            f"{result.name:<34} "
            f"{'PASS' if result.passed else 'FAIL':<5} "
            f"steps={result.metrics.steps:<3} "
            f"tools={result.metrics.tool_calls:<3} "
            f"time={result.duration_ms / 1000:.2f}s"
        )
    lines.extend(
        [
            "-" * 56,
            f"Success rate: {report.passed}/{report.total} ({report.success_rate * 100:.1f}%)",
            f"Average steps: {report.average_steps:.2f}",
            f"Average tool calls: {report.average_tool_calls:.2f}",
        ]
    )
    return "\n".join(lines)

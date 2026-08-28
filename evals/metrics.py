from __future__ import annotations

import json
from pathlib import Path

from .models import EvalMetrics


def collect_trace_metrics(
    trace_path: str | Path | None,
    *,
    fallback_steps: int = 0,
    fallback_tool_calls: int = 0,
    session_id: str | None = None,
) -> EvalMetrics:
    """Collect lightweight metrics from one append-only JSONL trace."""

    if trace_path is None:
        return EvalMetrics(
            steps=fallback_steps,
            tool_calls=fallback_tool_calls,
            session_id=session_id,
            trace_path=None,
        )

    path = Path(trace_path)
    model_calls = 0
    validation_attempts = 0
    error_events = 0
    model_duration_ms = 0.0
    tool_duration_ms = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    max_step = fallback_steps
    tool_calls = fallback_tool_calls

    observed_tool_calls = 0

    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue

            step = record.get("step")
            if isinstance(step, int):
                max_step = max(max_step, step)

            event = record.get("event")
            data = record.get("data", {})
            if not isinstance(data, dict):
                data = {}

            if event == "model_call":
                model_calls += 1
            elif event == "tool_call":
                observed_tool_calls += 1
                if data.get("tool_name") == "run_command":
                    arguments = data.get("arguments", {})
                    if (
                        isinstance(arguments, dict)
                        and arguments.get("purpose") in {"run", "test"}
                    ):
                        validation_attempts += 1
            elif event == "error":
                error_events += 1
            elif event == "model_response":
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                    model_duration_ms += float(duration)

                usage = data.get("usage", {})
                if isinstance(usage, dict):
                    prompt = usage.get("prompt_tokens")
                    completion = usage.get("completion_tokens")
                    total = usage.get("total_tokens")
                    if isinstance(prompt, int) and not isinstance(prompt, bool):
                        prompt_tokens += prompt
                    if isinstance(completion, int) and not isinstance(completion, bool):
                        completion_tokens += completion
                    if isinstance(total, int) and not isinstance(total, bool):
                        total_tokens += total
            elif event == "tool_result":
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                    tool_duration_ms += float(duration)

    if observed_tool_calls:
        tool_calls = observed_tool_calls

    return EvalMetrics(
        steps=max_step,
        tool_calls=tool_calls,
        model_calls=model_calls,
        validation_attempts=validation_attempts,
        error_events=error_events,
        model_duration_ms=model_duration_ms,
        tool_duration_ms=tool_duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        session_id=session_id,
        trace_path=str(path),
    )

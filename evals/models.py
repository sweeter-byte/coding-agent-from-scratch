from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AcceptanceSpec:
    """Independent command used to verify one evaluation case."""

    argv: tuple[str, ...]
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class EvalCase:
    """One reproducible coding-agent evaluation case."""

    name: str
    task: str
    case_dir: Path
    project_dir: Path
    acceptance: AcceptanceSpec
    max_steps: int = 12
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False


@dataclass(frozen=True)
class EvalMetrics:
    steps: int = 0
    tool_calls: int = 0
    model_calls: int = 0
    validation_attempts: int = 0
    error_events: int = 0
    model_duration_ms: float = 0.0
    tool_duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    session_id: str | None = None
    trace_path: str | None = None


@dataclass(frozen=True)
class EvalCaseResult:
    name: str
    passed: bool
    agent_completed: bool
    agent_result: str
    agent_error: str | None
    acceptance: AcceptanceResult
    metrics: EvalMetrics
    workspace: str
    duration_ms: float


@dataclass
class EvalRunReport:
    run_id: str
    results: list[EvalCaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def average_steps(self) -> float:
        if self.total == 0:
            return 0.0
        return sum(result.metrics.steps for result in self.results) / self.total

    @property
    def average_tool_calls(self) -> float:
        if self.total == 0:
            return 0.0
        return sum(result.metrics.tool_calls for result in self.results) / self.total

    @property
    def average_duration_ms(self) -> float:
        if self.total == 0:
            return 0.0
        return sum(result.duration_ms for result in self.results) / self.total

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from .models import AcceptanceResult, EvalCase


_SECRET_ENV_MARKERS = (
    "API_KEY",
    "ACCESS_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PRIVATE_KEY",
)


def _safe_environment(workspace: Path) -> dict[str, str]:
    """Build an acceptance environment without model credentials."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SECRET_ENV_MARKERS)
    }

    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(workspace)
        if not existing_pythonpath
        else str(workspace) + os.pathsep + existing_pythonpath
    )
    return environment


def expand_acceptance_argv(case: EvalCase, workspace: Path) -> tuple[str, ...]:
    """Expand deterministic placeholders without invoking a shell."""

    replacements = {
        "{python}": sys.executable,
        "{workspace}": str(workspace),
        "{case_dir}": str(case.case_dir),
    }

    expanded: list[str] = []
    for argument in case.acceptance.argv:
        value = argument
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        expanded.append(value)

    return tuple(expanded)


def run_acceptance(case: EvalCase, workspace: str | Path) -> AcceptanceResult:
    """Run the hidden/independent acceptance check for one case."""

    workspace_path = Path(workspace).resolve()
    argv = expand_acceptance_argv(case, workspace_path)
    started = perf_counter()

    try:
        completed = subprocess.run(
            list(argv),
            cwd=workspace_path,
            env=_safe_environment(workspace_path),
            capture_output=True,
            text=True,
            shell=False,
            timeout=case.acceptance.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (perf_counter() - started) * 1000
        return AcceptanceResult(
            passed=False,
            argv=argv,
            returncode=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            duration_ms=duration_ms,
            timed_out=True,
        )

    duration_ms = (perf_counter() - started) * 1000
    return AcceptanceResult(
        passed=completed.returncode == 0,
        argv=argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration_ms,
        timed_out=False,
    )

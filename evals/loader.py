from __future__ import annotations

import json
import re
from pathlib import Path

from .models import AcceptanceSpec, EvalCase


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def load_case(case_dir: str | Path) -> EvalCase:
    """Load and validate one evaluation case directory."""

    root = Path(case_dir).resolve()
    manifest_path = root / "case.json"
    project_dir = root / "project"

    if not manifest_path.is_file():
        raise ValueError(f"Missing evaluation manifest: {manifest_path}")

    if not project_dir.is_dir():
        raise ValueError(f"Missing evaluation project directory: {project_dir}")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {manifest_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Evaluation manifest must contain a JSON object.")

    name = data.get("name", root.name)
    if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
        raise ValueError("Evaluation case name must contain only letters, digits, '_' or '-'.")

    task = data.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ValueError(f"Evaluation case '{name}' has no valid task.")

    max_steps = data.get("max_steps", 12)
    if not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError(f"Evaluation case '{name}' has invalid max_steps.")

    tags_data = data.get("tags", [])
    if not isinstance(tags_data, list) or not all(isinstance(tag, str) and tag for tag in tags_data):
        raise ValueError(f"Evaluation case '{name}' has invalid tags.")

    acceptance_data = data.get("acceptance")
    if not isinstance(acceptance_data, dict):
        raise ValueError(f"Evaluation case '{name}' is missing acceptance settings.")

    argv = acceptance_data.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(argument, str) and argument for argument in argv)
    ):
        raise ValueError(f"Evaluation case '{name}' has invalid acceptance argv.")

    timeout_seconds = acceptance_data.get("timeout_seconds", 20.0)
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or timeout_seconds <= 0
    ):
        raise ValueError(f"Evaluation case '{name}' has invalid acceptance timeout.")

    return EvalCase(
        name=name,
        task=task.strip(),
        case_dir=root,
        project_dir=project_dir,
        max_steps=max_steps,
        tags=tuple(tags_data),
        acceptance=AcceptanceSpec(
            argv=tuple(argv),
            timeout_seconds=float(timeout_seconds),
        ),
    )


def discover_cases(
    cases_root: str | Path,
    selected_names: set[str] | None = None,
) -> list[EvalCase]:
    """Discover evaluation cases in deterministic name order."""

    root = Path(cases_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Evaluation cases directory does not exist: {root}")

    cases: list[EvalCase] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or not (child / "case.json").is_file():
            continue
        case = load_case(child)
        if selected_names is None or case.name in selected_names:
            cases.append(case)

    if selected_names is not None:
        discovered = {case.name for case in cases}
        missing = sorted(selected_names - discovered)
        if missing:
            raise ValueError("Unknown evaluation case(s): " + ", ".join(missing))

    return cases

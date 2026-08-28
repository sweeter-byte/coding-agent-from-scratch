from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationRecord:
    """
    Durable evidence that one workspace revision passed a local check.

    The runtime records the exact workspace fingerprint together with
    the command that succeeded. A later workspace change therefore
    cannot reuse stale validation evidence.
    """

    revision: str
    argv: list[str]
    purpose: str
    returncode: int
    step: int

    @classmethod
    def from_dict(
        cls,
        data: dict,
    ) -> "ValidationRecord":
        if not isinstance(data, dict):
            raise ValueError(
                "Validation record must be a dictionary."
            )

        revision = data.get("revision")
        purpose = data.get("purpose")
        argv = data.get("argv")
        returncode = data.get("returncode")
        step = data.get("step")

        if not isinstance(revision, str) or not revision:
            raise ValueError(
                "Validation record revision must be a non-empty string."
            )

        if purpose not in {"run", "test"}:
            raise ValueError(
                "Validation record purpose must be 'run' or 'test'."
            )

        if (
            not isinstance(argv, list)
            or not all(isinstance(item, str) for item in argv)
        ):
            raise ValueError(
                "Validation record argv must be a list of strings."
            )

        if isinstance(returncode, bool) or not isinstance(returncode, int):
            raise ValueError(
                "Validation record returncode must be an integer."
            )

        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or step < 0
        ):
            raise ValueError(
                "Validation record step must be a non-negative integer."
            )

        return cls(
            revision=revision,
            argv=list(argv),
            purpose=purpose,
            returncode=returncode,
            step=step,
        )

from dataclasses import dataclass, field

from .validation import ValidationRecord
from .working_memory import WorkingMemory


@dataclass
class AgentState:
    """
    Mutable runtime state for one CodingAgent task.

    The state is separated from CodingAgent so that termination rules,
    debugging logic, and future UI code can inspect the agent's current
    progress without depending on local variables inside run().

    write_version / validated_version remain as lightweight logical
    counters for observability and backward-compatible session restore.
    Workspace revisions provide the stronger correctness guarantee used
    by the runtime finish guard.
    """

    step: int = 0

    write_version: int = 0

    validated_version: int = -1

    current_revision: str | None = None

    validated_revision: str | None = None

    validation_records: list[ValidationRecord] = field(
        default_factory=list
    )

    working_memory: WorkingMemory = field(
        default_factory=WorkingMemory
    )

    total_tool_calls: int = 0

    consecutive_errors: int = 0

    last_tool_name: str | None = None

    last_error: str | None = None

    # ========================================================
    # Lifecycle
    # ========================================================

    def reset(self) -> None:
        self.step = 0

        self.write_version = 0

        self.validated_version = -1

        self.current_revision = None

        self.validated_revision = None

        self.validation_records = []

        self.working_memory.reset()

        self.total_tool_calls = 0

        self.consecutive_errors = 0

        self.last_tool_name = None

        self.last_error = None

    def restore(
        self,
        data: dict,
    ) -> None:
        """
        Restore runtime state from persisted session data.

        New revision fields are optional so sessions created before the
        revision feature can still be loaded. Once resumed, CodingAgent
        refreshes the actual workspace fingerprint and requires a fresh
        validation before completion when no persisted revision evidence
        exists.
        """

        if not isinstance(
            data,
            dict,
        ):
            raise TypeError(
                "state data must be a dictionary."
            )

        self.step = self._restore_int(
            data=data,
            key="step",
            default=0,
            minimum=0,
        )

        self.write_version = self._restore_int(
            data=data,
            key="write_version",
            default=0,
            minimum=0,
        )

        self.validated_version = self._restore_int(
            data=data,
            key="validated_version",
            default=-1,
            minimum=-1,
        )

        self.current_revision = self._restore_optional_string(
            data=data,
            key="current_revision",
        )

        self.validated_revision = self._restore_optional_string(
            data=data,
            key="validated_revision",
        )

        self.validation_records = self._restore_validation_records(
            data.get("validation_records", [])
        )

        working_memory_data = data.get(
            "working_memory"
        )

        if working_memory_data is None:
            # Backward compatibility for sessions created before
            # structured working memory existed.
            self.working_memory.reset()
        else:
            self.working_memory.restore(
                working_memory_data
            )

        self.total_tool_calls = self._restore_int(
            data=data,
            key="total_tool_calls",
            default=0,
            minimum=0,
        )

        self.consecutive_errors = self._restore_int(
            data=data,
            key="consecutive_errors",
            default=0,
            minimum=0,
        )

        self.last_tool_name = self._restore_optional_string(
            data=data,
            key="last_tool_name",
        )

        self.last_error = self._restore_optional_string(
            data=data,
            key="last_error",
        )

        if self.validated_version > self.write_version:
            raise ValueError(
                "validated_version cannot be greater "
                "than write_version."
            )

        if (
            self.validated_revision is not None
            and self.current_revision is None
        ):
            raise ValueError(
                "validated_revision requires current_revision."
            )

        if self.validation_records:
            last_record = self.validation_records[-1]

            if (
                self.validated_revision is not None
                and last_record.revision != self.validated_revision
            ):
                raise ValueError(
                    "validated_revision must match the latest "
                    "validation record."
                )

        # Revision fields in AgentState remain authoritative. This also
        # reconstructs useful memory facts when restoring an older session
        # that did not persist WorkingMemory yet.
        self.working_memory.sync_revisions(
            current_revision=self.current_revision,
            validated_revision=self.validated_revision,
        )

    def prepare_for_resume(
        self,
    ) -> None:
        """
        Clear transient failure state before resuming a session.

        Durable task progress such as step/write/validation evidence is
        intentionally preserved. A previous burst of errors should not
        cause the freshly resumed process to stop immediately.
        """

        self.consecutive_errors = 0
        self.last_error = None

    def begin_step(
        self,
        step: int,
    ) -> None:
        if step <= 0:
            raise ValueError(
                "step must be greater than 0."
            )

        self.step = step

    # ========================================================
    # Workspace revision
    # ========================================================

    def observe_workspace_revision(
        self,
        revision: str,
    ) -> None:
        """Record the latest filesystem fingerprint observed by runtime."""

        if not isinstance(revision, str) or not revision:
            raise ValueError(
                "workspace revision must be a non-empty string."
            )

        self.current_revision = revision

        self.working_memory.sync_revisions(
            current_revision=self.current_revision,
            validated_revision=self.validated_revision,
        )

    # ========================================================
    # Tool result
    # ========================================================

    def record_tool_result(
        self,
        tool_name: str,
        arguments: dict,
        result: dict,
        workspace_revision: str | None = None,
    ) -> None:
        """
        Update runtime state after one local tool execution.

        workspace_revision should be the post-execution fingerprint for
        tools that may change workspace contents. Recording the revision
        even after a failed command lets the runtime detect partial file
        changes caused before that command returned a non-zero status.
        """

        self.total_tool_calls += 1

        self.last_tool_name = (
            tool_name
        )

        if workspace_revision is not None:
            self.observe_workspace_revision(
                workspace_revision
            )

        ok = bool(
            result.get("ok")
        )

        # ----------------------------------------------------
        # Error state
        # ----------------------------------------------------

        if ok:
            self.consecutive_errors = 0
            self.last_error = None

        else:
            self.consecutive_errors += 1

            self.last_error = (
                self._extract_error(
                    result
                )
            )

        # ----------------------------------------------------
        # Source version
        # ----------------------------------------------------

        if (
            tool_name in {
                "write_file",
                "edit_file",
            }
            and ok
        ):
            self.write_version += 1

        # ----------------------------------------------------
        # Runtime validation
        # ----------------------------------------------------

        if (
            tool_name == "run_command"
            and ok
        ):
            purpose = arguments.get(
                "purpose"
            )

            if purpose in {
                "run",
                "test",
            }:
                self.validated_version = (
                    self.write_version
                )

                if workspace_revision is not None:
                    self.validated_revision = (
                        workspace_revision
                    )

                    self.validation_records.append(
                        ValidationRecord(
                            revision=workspace_revision,
                            argv=self._normalize_argv(
                                arguments.get("argv")
                            ),
                            purpose=purpose,
                            returncode=self._normalize_returncode(
                                result.get("returncode")
                            ),
                            step=self.step,
                        )
                    )

        # ----------------------------------------------------
        # Structured working memory
        # ----------------------------------------------------

        self.working_memory.record_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            step=self.step,
        )

        self.working_memory.sync_revisions(
            current_revision=self.current_revision,
            validated_revision=self.validated_revision,
        )

    # ========================================================
    # Runtime errors
    # ========================================================

    def record_runtime_error(
        self,
        error: str,
    ) -> None:
        self.consecutive_errors += 1
        self.last_error = error
        self.working_memory.last_error = error

    # ========================================================
    # Derived states
    # ========================================================

    @property
    def has_written_source(
        self,
    ) -> bool:
        return (
            self.write_version > 0
        )

    @property
    def latest_version_validated(
        self,
    ) -> bool:
        """
        Return whether the current workspace has valid evidence.

        Revision-aware state takes precedence. The logical integer
        counters are retained only as a fallback for older persisted
        sessions and direct unit-level state construction.
        """

        if self.current_revision is not None:
            return (
                self.write_version > 0
                and self.validated_revision is not None
                and self.validated_revision
                == self.current_revision
            )

        return (
            self.write_version > 0
            and self.validated_version
            == self.write_version
        )

    @property
    def workspace_changed_after_validation(
        self,
    ) -> bool:
        return (
            self.current_revision is not None
            and self.validated_revision is not None
            and self.current_revision
            != self.validated_revision
        )

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _restore_int(
        data: dict,
        key: str,
        default: int,
        minimum: int,
    ) -> int:
        value = data.get(
            key,
            default,
        )

        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
        ):
            raise ValueError(
                f"Invalid persisted state field '{key}'."
            )

        if value < minimum:
            raise ValueError(
                f"Persisted state field '{key}' "
                f"must be >= {minimum}."
            )

        return value

    @staticmethod
    def _restore_optional_string(
        data: dict,
        key: str,
    ) -> str | None:
        value = data.get(
            key
        )

        if value is None:
            return None

        if not isinstance(
            value,
            str,
        ) or not value:
            raise ValueError(
                f"Invalid persisted state field '{key}'."
            )

        return value

    @staticmethod
    def _restore_validation_records(
        value: object,
    ) -> list[ValidationRecord]:
        if not isinstance(value, list):
            raise ValueError(
                "Invalid persisted state field 'validation_records'."
            )

        return [
            ValidationRecord.from_dict(item)
            for item in value
        ]

    @staticmethod
    def _normalize_argv(
        value: object,
    ) -> list[str]:
        if not isinstance(value, list):
            return []

        return [
            str(item)
            for item in value
        ]

    @staticmethod
    def _normalize_returncode(
        value: object,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 0

        return value

    @staticmethod
    def _extract_error(
        result: dict,
    ) -> str:
        error = result.get(
            "error"
        )

        if error:
            return str(error)

        stderr = result.get(
            "stderr"
        )

        if stderr:
            return str(stderr)

        return (
            "Tool execution failed."
        )

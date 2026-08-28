from dataclasses import dataclass


@dataclass
class AgentState:
    """
    Mutable runtime state for one CodingAgent task.

    The state is separated from CodingAgent so that termination rules,
    debugging logic, and future UI code can inspect the agent's current
    progress without depending on local variables inside run().
    """

    step: int = 0

    write_version: int = 0

    validated_version: int = -1

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

        self.total_tool_calls = 0

        self.consecutive_errors = 0

        self.last_tool_name = None

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
    # Tool result
    # ========================================================

    def record_tool_result(
        self,
        tool_name: str,
        arguments: dict,
        result: dict,
    ) -> None:
        """
        Update runtime state after one local tool execution.
        """

        self.total_tool_calls += 1

        self.last_tool_name = (
            tool_name
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
            tool_name == "write_file"
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

    # ========================================================
    # Runtime errors
    # ========================================================

    def record_runtime_error(
        self,
        error: str,
    ) -> None:
        self.consecutive_errors += 1
        self.last_error = error

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
        return (
            self.write_version > 0
            and self.validated_version
            == self.write_version
        )

    # ========================================================
    # Helpers
    # ========================================================

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
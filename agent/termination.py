from dataclasses import dataclass
from enum import Enum

from .state import AgentState


class TerminationAction(
    str,
    Enum,
):
    CONTINUE = "continue"
    FINISH = "finish"
    STOP = "stop"


@dataclass(frozen=True)
class TerminationDecision:
    action: TerminationAction
    reason: str
    feedback: str = ""

    @property
    def can_finish(
        self,
    ) -> bool:
        return (
            self.action
            == TerminationAction.FINISH
        )

    @property
    def should_stop(
        self,
    ) -> bool:
        return (
            self.action
            == TerminationAction.STOP
        )


class TerminationPolicy:
    """
    Decide whether the autonomous agent loop may continue or finish.

    Current rules:

    1. The model cannot finish before creating source code.
    2. Successful validation must match the current workspace revision.
    3. Too many consecutive runtime/tool errors stop the loop.
    4. max_steps provides the final hard upper bound.
    """

    def __init__(
        self,
        max_steps: int,
        max_consecutive_errors: int = 4,
    ) -> None:
        if max_steps <= 0:
            raise ValueError(
                "max_steps must be greater than 0."
            )

        if max_consecutive_errors <= 0:
            raise ValueError(
                "max_consecutive_errors must "
                "be greater than 0."
            )

        self.max_steps = max_steps

        self.max_consecutive_errors = (
            max_consecutive_errors
        )

    # ========================================================
    # Model wants to finish
    # ========================================================

    def evaluate_finish_request(
        self,
        state: AgentState,
    ) -> TerminationDecision:
        """
        Evaluate a response containing no tool calls.

        No tool call means the model is attempting to return
        its final answer.

        But the local runtime makes the final decision.
        """

        # ----------------------------------------------------
        # Guard 1:
        # source code must exist
        # ----------------------------------------------------

        if not state.has_written_source:
            return TerminationDecision(
                action=(
                    TerminationAction.CONTINUE
                ),
                reason=(
                    "source_not_created"
                ),
                feedback=(
                    "You have not created the "
                    "requested source file yet. "
                    "Continue the task using tools."
                ),
            )

        # ----------------------------------------------------
        # Guard 2:
        # validation evidence must match current workspace
        # ----------------------------------------------------

        if state.workspace_changed_after_validation:
            return TerminationDecision(
                action=(
                    TerminationAction.CONTINUE
                ),
                reason=(
                    "workspace_changed_after_validation"
                ),
                feedback=(
                    "The workspace changed after the last "
                    "successful validation. Previous validation "
                    "evidence is stale. Re-run the appropriate "
                    "command with purpose='run' or purpose='test' "
                    "before finishing."
                ),
            )

        if (
            not state
            .latest_version_validated
        ):
            return TerminationDecision(
                action=(
                    TerminationAction.CONTINUE
                ),
                reason=(
                    "latest_version_not_validated"
                ),
                feedback=(
                    "The latest source-code version has not passed "
                    "successful runtime validation for the current "
                    "workspace revision. Continue using run_command "
                    "with purpose='run' or purpose='test'."
                ),
            )

        # ----------------------------------------------------
        # Agent may finish
        # ----------------------------------------------------

        return TerminationDecision(
            action=(
                TerminationAction.FINISH
            ),
            reason="task_validated",
        )

    # ========================================================
    # Runtime hard-stop conditions
    # ========================================================

    def evaluate_runtime(
        self,
        state: AgentState,
    ) -> TerminationDecision:
        if (
            state.consecutive_errors
            >= self.max_consecutive_errors
        ):
            return TerminationDecision(
                action=(
                    TerminationAction.STOP
                ),
                reason=(
                    "too_many_consecutive_errors"
                ),
                feedback=(
                    "Agent stopped after too many "
                    "consecutive errors. "
                    "Last error: "
                    f"{state.last_error or 'unknown error'}"
                ),
            )

        return TerminationDecision(
            action=(
                TerminationAction.CONTINUE
            ),
            reason=(
                "runtime_can_continue"
            ),
        )

    # ========================================================
    # Maximum steps
    # ========================================================

    def max_steps_error(
        self,
    ) -> str:
        return (
            "Agent reached the maximum "
            "number of steps "
            f"({self.max_steps}) "
            "without completing the task."
        )
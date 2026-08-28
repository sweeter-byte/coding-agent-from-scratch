import json
import platform

from pathlib import Path
from time import perf_counter

from .config import (
    AgentConfig,
    PROJECT_ROOT,
)

from .context import (
    ContextManager,
)

from .error_handler import (
    ErrorHandler,
)

from .history import (
    ConversationHistory,
)

from .llm_client import (
    LLMClient,
)

from .parser import (
    ModelOutputError,
    ParsedToolCall,
    ResponseParser,
)

from .state import (
    AgentState,
)

from .termination import (
    TerminationPolicy,
)

from storage import (
    SessionStore,
    TraceLogger,
)

from security import (
    SensitiveDataPolicy,
)

from tools.registry import (
    ToolRegistry,
)


# ============================================================
# Prompt loader
# ============================================================

def load_system_prompt() -> str:
    """
    Load:

        prompts/system_prompt.md
    """

    prompt_path = (
        PROJECT_ROOT
        / "prompts"
        / "system_prompt.md"
    )

    if not prompt_path.exists():
        raise FileNotFoundError(
            "System prompt not found: "
            f"{prompt_path}"
        )

    return prompt_path.read_text(
        encoding="utf-8"
    )


# ============================================================
# Coding Agent
# ============================================================

class CodingAgent:
    """
    Autonomous coding-agent orchestrator.

    CodingAgent itself coordinates the agent loop.

    Core responsibilities are delegated to independent modules:

    - ConversationHistory
        complete in-memory conversation history

    - ContextManager
        model-input context selection

    - WorkingMemory (inside AgentState)
        deterministic task-state summary derived from tool results

    - LLMClient
        model API access

    - ResponseParser
        model-output parsing

    - AgentState
        runtime state

    - TerminationPolicy
        loop termination rules

    - ErrorHandler
        retries and structured errors

    - ToolRegistry
        local tool dispatch

    - SessionStore
        durable session persistence

    - TraceLogger
        runtime observability and debugging traces
    """

    def __init__(
        self,
        workspace: str = "workspace",
        max_steps: int = 12,
        config: AgentConfig | None = None,
    ) -> None:

        # ----------------------------------------------------
        # Configuration
        # ----------------------------------------------------

        if config is None:
            config = (
                AgentConfig.from_env(
                    workspace=workspace,
                    max_steps=max_steps,
                )
            )

        self.config = config

        # ----------------------------------------------------
        # Model
        # ----------------------------------------------------

        self.llm_client = LLMClient(
            config=self.config
        )

        # ----------------------------------------------------
        # Sensitive-data policy
        # ----------------------------------------------------

        self.sensitive_data_policy = (
            SensitiveDataPolicy()
        )

        # ----------------------------------------------------
        # Tool system
        # ----------------------------------------------------

        self.tool_registry = (
            ToolRegistry(
                workspace=(
                    self.config.workspace
                ),
                sensitive_data_policy=(
                    self.sensitive_data_policy
                ),
            )
        )

        # ----------------------------------------------------
        # Conversation history
        # ----------------------------------------------------

        self.history = (
            ConversationHistory()
        )

        # ----------------------------------------------------
        # Context management
        # ----------------------------------------------------

        self.context_manager = (
            ContextManager(
                max_context_messages=(
                    self.config
                    .max_context_messages
                )
            )
        )

        # ----------------------------------------------------
        # Model output parser
        # ----------------------------------------------------

        self.response_parser = (
            ResponseParser()
        )

        # ----------------------------------------------------
        # Runtime state
        # ----------------------------------------------------

        self.state = (
            AgentState()
        )

        # ----------------------------------------------------
        # Termination policy
        # ----------------------------------------------------

        self.termination_policy = (
            TerminationPolicy(
                max_steps=(
                    self.config.max_steps
                ),
                max_consecutive_errors=(
                    self.config
                    .max_consecutive_errors
                ),
            )
        )

        # ----------------------------------------------------
        # Error handling
        # ----------------------------------------------------

        self.error_handler = (
            ErrorHandler(
                max_model_retries=(
                    self.config
                    .max_model_retries
                )
            )
        )

        # ----------------------------------------------------
        # Persistent session storage
        # ----------------------------------------------------

        self.session_store = (
            SessionStore()
        )

        # TraceLogger is bound to a persistent session ID. New tasks
        # create a new trace; resumed tasks append to the same trace.
        self.trace_logger: (
            TraceLogger | None
        ) = None

        self.session_id: (
            str | None
        ) = None

        self.current_task: (
            str | None
        ) = None

        # ----------------------------------------------------
        # Prompt
        # ----------------------------------------------------

        self.system_prompt = (
            load_system_prompt()
        )

    # ========================================================
    # Session lifecycle
    # ========================================================

    def run(
        self,
        user_task: str,
    ) -> str:
        """
        Start a new coding task and execute the autonomous loop.
        """

        self._initialize_new_session(
            user_task
        )

        return self._execute_loop(
            start_step=1
        )

    def resume(
        self,
        session_id: str,
    ) -> str:
        """
        Resume a previously persisted non-completed session.

        The same session ID, conversation history, workspace and
        durable AgentState are reused. The next model call starts at
        the step following the last persisted step.
        """

        start_step = (
            self._restore_session(
                session_id
            )
        )

        return self._execute_loop(
            start_step=start_step
        )

    def _initialize_new_session(
        self,
        user_task: str,
    ) -> None:
        """
        Initialize history, state, persistence and tracing for a new
        task.
        """

        if (
            not isinstance(
                user_task,
                str,
            )
            or not user_task.strip()
        ):
            raise ValueError(
                "user_task cannot be empty."
            )

        self.current_task = (
            user_task.strip()
        )

        self.state.reset()

        # Bind runtime state to the actual initial filesystem snapshot.
        # A fresh task still cannot finish until source has been written
        # and that resulting revision has been validated.
        self.state.observe_workspace_revision(
            self._calculate_workspace_revision()
        )

        system_prompt = (
            self._build_system_prompt()
        )

        self.history.reset(
            system_prompt=system_prompt,
            user_task=self.current_task,
        )

        self.session_id = (
            self.session_store
            .create_session(
                metadata={
                    "task": self.current_task,
                    "model": (
                        self.config.model
                    ),
                    "workspace": str(
                        self.config.workspace
                    ),
                    "status": "running",
                    "error": None,
                }
            )
        )

        self.trace_logger = (
            TraceLogger(
                run_id=self.session_id
            )
        )

        self._save_session(
            status="running"
        )

        self.trace_logger.log_agent_start(
            task=self.current_task,
            model=self.config.model,
            workspace=(
                self.config.workspace
            ),
        )

    def _restore_session(
        self,
        session_id: str,
    ) -> int:
        """
        Restore a persisted session and return the next step number.

        Conversation state and filesystem state must refer to the same
        workspace. Otherwise model history could describe files that
        do not exist in the workspace currently exposed to tools.
        """

        session = (
            self.session_store
            .load(
                session_id
            )
        )

        metadata = session.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            raise ValueError(
                "Invalid session metadata."
            )

        previous_status = (
            metadata.get(
                "status"
            )
        )

        if previous_status == "completed":
            raise ValueError(
                "Completed sessions cannot be resumed."
            )

        allowed_statuses = {
            None,
            "running",
            "interrupted",
            "failed",
        }

        if (
            previous_status
            not in allowed_statuses
        ):
            raise ValueError(
                "Session has an unsupported status: "
                f"{previous_status}"
            )

        task = metadata.get(
            "task"
        )

        if (
            not isinstance(
                task,
                str,
            )
            or not task.strip()
        ):
            raise ValueError(
                "Stored session has no valid task."
            )

        stored_workspace = (
            metadata.get(
                "workspace"
            )
        )

        if stored_workspace is not None:
            if not isinstance(
                stored_workspace,
                str,
            ):
                raise ValueError(
                    "Stored session workspace is invalid."
                )

            stored_workspace_path = (
                Path(
                    stored_workspace
                )
                .expanduser()
                .resolve()
            )

            current_workspace_path = (
                self.config.workspace
                .expanduser()
                .resolve()
            )

            if (
                stored_workspace_path
                != current_workspace_path
            ):
                raise ValueError(
                    "Session workspace does not match "
                    "the current workspace. "
                    f"Stored: {stored_workspace_path}; "
                    f"Current: {current_workspace_path}"
                )

        messages = session.get(
            "messages",
            [],
        )

        if not isinstance(
            messages,
            list,
        ):
            raise ValueError(
                "Invalid session messages."
            )

        state_data = session.get(
            "state",
            {},
        )

        if not isinstance(
            state_data,
            dict,
        ):
            raise ValueError(
                "Invalid persisted AgentState."
            )

        # Restore durable in-memory state only after all basic session
        # structure checks have passed.
        self.history.restore(
            messages
        )

        self.state.restore(
            state_data
        )

        persisted_revision = (
            self.state.current_revision
        )

        actual_revision = (
            self._calculate_workspace_revision()
        )

        workspace_changed = (
            persisted_revision is not None
            and persisted_revision != actual_revision
        )

        # Always trust the current filesystem over persisted metadata.
        # If it changed, validated_revision intentionally remains bound
        # to the old snapshot so the finish guard requires revalidation.
        self.state.observe_workspace_revision(
            actual_revision
        )

        restored_step = (
            self.state.step
        )

        # A new process should not inherit an old consecutive-error
        # streak, but it must keep durable task progress.
        self.state.prepare_for_resume()

        self.current_task = (
            task.strip()
        )

        self.session_id = session_id

        self.trace_logger = (
            TraceLogger(
                run_id=session_id
            )
        )

        if workspace_changed:
            feedback = (
                "The workspace contents changed since this session "
                "was last persisted. Previous validation evidence "
                "is no longer sufficient; inspect the current files "
                "and re-run validation before finishing."
            )

            self.history.add_runtime_feedback(
                feedback
            )

            self.trace_logger.log_runtime_feedback(
                step=restored_step,
                feedback=feedback,
                reason=(
                    "workspace_changed_since_session"
                ),
            )

        next_step = (
            restored_step + 1
        )

        if (
            next_step
            > self.config.max_steps
        ):
            self.trace_logger.log(
                "session_resume_rejected",
                step=restored_step,
                previous_status=(
                    previous_status
                ),
                configured_max_steps=(
                    self.config.max_steps
                ),
            )

            raise RuntimeError(
                "This session has already reached "
                f"step {restored_step}. Resume it with "
                "a larger --max-steps value."
            )

        self._save_session(
            status="running"
        )

        self.trace_logger.log_session_resume(
            restored_step=restored_step,
            next_step=next_step,
            previous_status=(
                previous_status
            ),
        )

        return next_step

    # ========================================================
    # Main Agent Loop
    # ========================================================

    def _execute_loop(
        self,
        start_step: int,
    ) -> str:
        """
        Execute the shared autonomous loop used by run() and resume().

        Main loop:

            current context
                  ↓
                model
                  ↓
            parsed response
                  ↓
              tool calls
                  ↓
           local execution
                  ↓
             observations
                  ↓
          persist + trace
                  ↓
            next context
                  ↓
                 ...
                  ↓
         termination policy
        """

        if start_step <= 0:
            raise ValueError(
                "start_step must be greater than 0."
            )

        if (
            self.session_id is None
            or self.trace_logger is None
            or self.current_task is None
        ):
            raise RuntimeError(
                "Agent session is not initialized."
            )

        try:
            tool_schemas = (
                self.tool_registry
                .get_schemas()
            )

            for step in range(
                start_step,
                self.config.max_steps + 1,
            ):

                self.state.begin_step(
                    step
                )

                self._print_step_header(
                    step
                )

                self.trace_logger.log_agent_step(
                    step=step
                )

                context = (
                    self.context_manager
                    .build(
                        self.history,
                        working_memory=(
                            self.state.working_memory
                        ),
                    )
                )

                self.trace_logger.log_model_call(
                    step=step,
                    model=(
                        self.config.model
                    ),
                    message_count=len(
                        context
                    ),
                    tool_count=len(
                        tool_schemas
                    ),
                )

                model_start = (
                    perf_counter()
                )

                response = (
                    self.error_handler
                    .run_model_call(
                        lambda: (
                            self.llm_client
                            .create_completion(
                                messages=context,
                                tools=tool_schemas,
                            )
                        )
                    )
                )

                model_duration_ms = (
                    (
                        perf_counter()
                        - model_start
                    )
                    * 1000
                )

                try:
                    parsed = (
                        self.response_parser
                        .parse(
                            response
                        )
                    )

                except ModelOutputError as exc:

                    self.state.record_runtime_error(
                        str(exc)
                    )

                    self.trace_logger.log_error(
                        error=str(exc),
                        source="response_parser",
                        step=step,
                        recoverable=True,
                    )

                    feedback = (
                        "The previous model response "
                        "could not be parsed by the "
                        "local runtime: "
                        f"{exc}. "
                        "Please try again."
                    )

                    self.history.add_runtime_feedback(
                        feedback
                    )

                    self.trace_logger.log_runtime_feedback(
                        step=step,
                        feedback=feedback,
                        reason=(
                            "model_output_parse_error"
                        ),
                    )

                    self._save_session(
                        status="running"
                    )

                    runtime_decision = (
                        self.termination_policy
                        .evaluate_runtime(
                            self.state
                        )
                    )

                    if (
                        runtime_decision
                        .should_stop
                    ):
                        raise RuntimeError(
                            runtime_decision
                            .feedback
                        )

                    continue

                usage = getattr(
                    response,
                    "usage",
                    None,
                )

                self.trace_logger.log_model_response(
                    step=step,
                    content=(
                        parsed.content
                    ),
                    tool_call_count=len(
                        parsed.tool_calls
                    ),
                    usage=usage,
                    duration_ms=(
                        model_duration_ms
                    ),
                )

                self.history.add_assistant_message(
                    parsed.assistant_message
                )

                self._save_session(
                    status="running"
                )

                if not parsed.tool_calls:

                    # Re-read the filesystem at the exact finish boundary.
                    # This catches manual edits or command-side changes that
                    # happened after the last successful validation.
                    self.state.observe_workspace_revision(
                        self._calculate_workspace_revision()
                    )

                    decision = (
                        self.termination_policy
                        .evaluate_finish_request(
                            self.state
                        )
                    )

                    if decision.can_finish:

                        final_result = (
                            parsed.content
                            or (
                                "Task completed "
                                "successfully."
                            )
                        )

                        self.trace_logger.log_agent_finish(
                            step=step,
                            result=final_result,
                        )

                        self._save_session(
                            status="completed"
                        )

                        return final_result

                    print()

                    print(
                        "[Runtime Guard] "
                        + decision.reason
                    )

                    self.history.add_runtime_feedback(
                        decision.feedback
                    )

                    self.trace_logger.log_runtime_feedback(
                        step=step,
                        feedback=(
                            decision.feedback
                        ),
                        reason=(
                            decision.reason
                        ),
                    )

                    self._save_session(
                        status="running"
                    )

                    continue

                for tool_call in (
                    parsed.tool_calls
                ):

                    self._handle_tool_call(
                        tool_call=tool_call
                    )

                runtime_decision = (
                    self.termination_policy
                    .evaluate_runtime(
                        self.state
                    )
                )

                if (
                    runtime_decision
                    .should_stop
                ):
                    raise RuntimeError(
                        runtime_decision
                        .feedback
                    )

            raise RuntimeError(
                self.termination_policy
                .max_steps_error()
            )

        except KeyboardInterrupt:

            if self.trace_logger is not None:

                self.trace_logger.log_agent_stop(
                    step=self.state.step,
                    reason=(
                        "Agent interrupted "
                        "by user."
                    ),
                )

            self._save_session(
                status="interrupted"
            )

            raise

        except Exception as exc:

            if self.trace_logger is not None:

                self.trace_logger.log_error(
                    error=str(exc),
                    source="coding_agent",
                    step=(
                        self.state.step
                        if self.state.step > 0
                        else None
                    ),
                    recoverable=False,
                )

                self.trace_logger.log_agent_stop(
                    step=self.state.step,
                    reason=str(exc),
                )

            self._save_session(
                status="failed",
                error=str(exc),
            )

            raise

    # ========================================================
    # Tool-call handling
    # ========================================================

    def _handle_tool_call(
        self,
        tool_call: ParsedToolCall,
    ) -> None:

        tool_name = (
            tool_call.name
        )

        print()

        print(
            f"[Tool Call] {tool_name}"
        )

        # ====================================================
        # Invalid model-generated arguments
        # ====================================================

        if not tool_call.is_valid:

            if self.trace_logger is not None:

                self.trace_logger.log_tool_call(
                    step=self.state.step,
                    tool_name=tool_name,
                    arguments={},
                    tool_call_id=(
                        tool_call.id
                    ),
                )

                self.trace_logger.log_error(
                    error=(
                        tool_call.error
                        or (
                            "Invalid "
                            "tool call."
                        )
                    ),
                    source=(
                        "tool_argument_parser"
                    ),
                    step=self.state.step,
                    recoverable=True,
                )

            tool_result = (
                self.error_handler
                .build_tool_error(
                    error=(
                        tool_call.error
                        or (
                            "Invalid "
                            "tool call."
                        )
                    ),
                    tool_name=(
                        tool_name
                    ),
                )
            )

            tool_result = (
                self.sensitive_data_policy
                .redact_text(tool_result)
            )

            result_data = (
                self.error_handler
                .parse_tool_result(
                    tool_result
                )
            )

            # -----------------------------------------------
            # Update runtime state
            # -----------------------------------------------

            self.state.record_tool_result(
                tool_name=tool_name,
                arguments={},
                result=result_data,
            )

            # -----------------------------------------------
            # Feed observation back to model
            # -----------------------------------------------

            self.history.add_tool_result(
                tool_call_id=(
                    tool_call.id
                ),
                content=(
                    tool_result
                ),
            )

            # -----------------------------------------------
            # Trace result
            # -----------------------------------------------

            if self.trace_logger is not None:

                self.trace_logger.log_tool_result(
                    step=self.state.step,
                    tool_name=tool_name,
                    result=result_data,
                    ok=False,
                    tool_call_id=(
                        tool_call.id
                    ),
                )

            # -----------------------------------------------
            # Persist after tool observation
            # -----------------------------------------------

            self._save_session(
                status="running"
            )

            self._print_tool_result(
                tool_result
            )

            return

        # ====================================================
        # Valid tool call
        # ====================================================

        arguments = (
            tool_call.arguments
            or {}
        )

        print(
            json.dumps(
                self.sensitive_data_policy
                .redact_data(arguments),
                ensure_ascii=False,
                indent=2,
            )
        )

        # ----------------------------------------------------
        # Trace tool call before local execution
        # ----------------------------------------------------

        if self.trace_logger is not None:

            self.trace_logger.log_tool_call(
                step=self.state.step,
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=(
                    tool_call.id
                ),
            )

        # ----------------------------------------------------
        # Local tool execution
        # ----------------------------------------------------

        tool_start = (
            perf_counter()
        )

        try:
            tool_result = (
                self.tool_registry
                .execute(
                    name=(
                        tool_name
                    ),
                    arguments=(
                        arguments
                    ),
                )
            )

        except Exception as exc:
            # ToolRegistry already handles ordinary tool errors.
            #
            # This additional boundary prevents an unexpected
            # registry implementation error from escaping without
            # producing a structured tool observation.

            tool_result = (
                self.error_handler
                .build_tool_error(
                    error=str(exc),
                    tool_name=(
                        tool_name
                    ),
                )
            )

        tool_duration_ms = (
            (
                perf_counter()
                - tool_start
            )
            * 1000
        )

        # ----------------------------------------------------
        # Redact result before state/history/persistence
        # ----------------------------------------------------

        tool_result = (
            self.sensitive_data_policy
            .redact_text(tool_result)
        )

        # ----------------------------------------------------
        # Parse structured tool result
        # ----------------------------------------------------

        result_data = (
            self.error_handler
            .parse_tool_result(
                tool_result
            )
        )

        # ----------------------------------------------------
        # Update AgentState + workspace revision
        # ----------------------------------------------------

        workspace_revision = None

        if tool_name in {
            "write_file",
            "edit_file",
            "run_command",
        }:
            workspace_revision = (
                self._calculate_workspace_revision()
            )

        validation_count_before = len(
            self.state.validation_records
        )

        self.state.record_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            result=result_data,
            workspace_revision=(
                workspace_revision
            ),
        )

        if (
            self.trace_logger is not None
            and len(self.state.validation_records)
            > validation_count_before
        ):
            record = (
                self.state.validation_records[-1]
            )

            self.trace_logger.log(
                "workspace_validation",
                step=record.step,
                revision=record.revision,
                argv=record.argv,
                purpose=record.purpose,
                returncode=record.returncode,
            )

        # ----------------------------------------------------
        # Feed observation back to LLM
        # ----------------------------------------------------

        self.history.add_tool_result(
            tool_call_id=(
                tool_call.id
            ),
            content=(
                tool_result
            ),
        )

        # ----------------------------------------------------
        # Trace tool result
        # ----------------------------------------------------

        if self.trace_logger is not None:

            self.trace_logger.log_tool_result(
                step=self.state.step,
                tool_name=tool_name,
                result=result_data,
                ok=bool(
                    result_data.get(
                        "ok"
                    )
                ),
                duration_ms=(
                    tool_duration_ms
                ),
                tool_call_id=(
                    tool_call.id
                ),
            )

        # ----------------------------------------------------
        # Persist history + state after each tool call
        # ----------------------------------------------------

        self._save_session(
            status="running"
        )

        self._print_tool_result(
            tool_result
        )

    # ========================================================
    # Workspace revision
    # ========================================================

    def _calculate_workspace_revision(
        self,
    ) -> str:
        """Return the current deterministic workspace fingerprint."""

        return (
            self.tool_registry
            .workspace
            .calculate_revision()
        )

    # ========================================================
    # Persistent session
    # ========================================================

    def _save_session(
        self,
        status: str,
        error: str | None = None,
    ) -> None:
        """
        Persist the complete conversation history and runtime state.

        This method is called repeatedly during execution rather than
        only when the task finishes, so partial progress survives a
        later runtime failure.
        """

        if self.session_id is None:
            return

        metadata = {
            "status": status,
            # Always write the error field so a resumed/running or
            # completed session clears a stale error from a previous
            # failed snapshot.
            "error": error,
        }

        self.session_store.save_history(
            session_id=(
                self.session_id
            ),
            history=self.history,
            metadata=metadata,
            state=self.state,
        )

    # ========================================================
    # System prompt
    # ========================================================

    def _build_system_prompt(
        self,
    ) -> str:

        current_os = (
            platform.system()
        )

        return (
            self.system_prompt
            + "\n\n"
            + (
                "Current operating system: "
                f"{current_os}"
            )
        )

    # ========================================================
    # CLI output
    # ========================================================

    def _print_step_header(
        self,
        step: int,
    ) -> None:

        print()

        print(
            "========================================"
        )

        print(
            f"Agent Step "
            f"{step}/{self.config.max_steps}"
        )

        print(
            "========================================"
        )

    def _print_tool_result(
        self,
        tool_result: str,
    ) -> None:

        print()

        print(
            "[Tool Result]"
        )

        print(
            self.sensitive_data_policy
            .redact_text(tool_result)
        )
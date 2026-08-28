import json
import platform

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
        # Tool system
        # ----------------------------------------------------

        self.tool_registry = (
            ToolRegistry(
                workspace=(
                    self.config.workspace
                )
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

        # A new TraceLogger is created for every run(),
        # because every task should have an independent trace.
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
    # Main Agent Loop
    # ========================================================

    def run(
        self,
        user_task: str,
    ) -> str:
        """
        Execute one coding task.

        Main loop:

            initialize session
                    ↓
                context
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

        if not user_task.strip():
            raise ValueError(
                "user_task cannot be empty."
            )

        self.current_task = user_task

        # ----------------------------------------------------
        # Reset runtime state
        # ----------------------------------------------------

        self.state.reset()

        # ----------------------------------------------------
        # Initialize conversation
        # ----------------------------------------------------

        system_prompt = (
            self._build_system_prompt()
        )

        self.history.reset(
            system_prompt=system_prompt,
            user_task=user_task,
        )

        # ----------------------------------------------------
        # Create persistent session
        # ----------------------------------------------------

        self.session_id = (
            self.session_store
            .create_session(
                metadata={
                    "task": user_task,
                    "model": (
                        self.config.model
                    ),
                    "workspace": str(
                        self.config.workspace
                    ),
                    "status": "running",
                }
            )
        )

        # ----------------------------------------------------
        # Trace uses the same ID as the session
        # ----------------------------------------------------

        self.trace_logger = (
            TraceLogger(
                run_id=self.session_id
            )
        )

        # ----------------------------------------------------
        # Persist initial history immediately
        # ----------------------------------------------------

        self._save_session(
            status="running"
        )

        self.trace_logger.log_agent_start(
            task=user_task,
            model=self.config.model,
            workspace=(
                self.config.workspace
            ),
        )

        try:
            # ------------------------------------------------
            # Obtain schemas through ToolRegistry
            # ------------------------------------------------

            tool_schemas = (
                self.tool_registry
                .get_schemas()
            )

            # =================================================
            # Agent loop
            # =================================================

            for step in range(
                1,
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

                # --------------------------------------------
                # Build current LLM context
                # --------------------------------------------

                context = (
                    self.context_manager
                    .build(
                        self.history
                    )
                )

                # --------------------------------------------
                # Trace model request
                # --------------------------------------------

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

                # --------------------------------------------
                # Call model
                # --------------------------------------------

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

                # --------------------------------------------
                # Parse model output
                # --------------------------------------------

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

                # --------------------------------------------
                # Trace successful model response
                # --------------------------------------------

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

                # --------------------------------------------
                # Save assistant message to history
                # --------------------------------------------

                self.history.add_assistant_message(
                    parsed.assistant_message
                )

                # Persist immediately.
                #
                # Even if execution crashes before tool execution,
                # the model response itself is already preserved.
                self._save_session(
                    status="running"
                )

                # =================================================
                # No tool calls:
                # model attempts to finish
                # =================================================

                if not parsed.tool_calls:

                    decision = (
                        self.termination_policy
                        .evaluate_finish_request(
                            self.state
                        )
                    )

                    # ----------------------------------------
                    # Runtime accepts completion
                    # ----------------------------------------

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

                    # ----------------------------------------
                    # Runtime rejects premature completion
                    # ----------------------------------------

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

                # =================================================
                # Execute tool calls
                # =================================================

                for tool_call in (
                    parsed.tool_calls
                ):

                    self._handle_tool_call(
                        tool_call=tool_call
                    )

                # --------------------------------------------
                # Runtime termination check
                # --------------------------------------------

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

            # =================================================
            # Maximum-step termination
            # =================================================

            raise RuntimeError(
                self.termination_policy
                .max_steps_error()
            )

        # ====================================================
        # User interruption
        # ====================================================

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

        # ====================================================
        # Fatal runtime error
        # ====================================================

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
                arguments,
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
        # Parse structured tool result
        # ----------------------------------------------------

        result_data = (
            self.error_handler
            .parse_tool_result(
                tool_result
            )
        )

        # ----------------------------------------------------
        # Update AgentState
        # ----------------------------------------------------

        self.state.record_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            result=result_data,
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
        }

        if error is not None:
            metadata[
                "error"
            ] = error

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

    @staticmethod
    def _print_tool_result(
        tool_result: str,
    ) -> None:

        print()

        print(
            "[Tool Result]"
        )

        print(
            tool_result
        )
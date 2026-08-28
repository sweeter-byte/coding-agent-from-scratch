import json
import platform

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
    ResponseParser,
)

from .state import (
    AgentState,
)

from .termination import (
    TerminationPolicy,
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

    CodingAgent itself only coordinates the main loop.

    Important logic is delegated to independent modules:

    - ConversationHistory
        complete local history

    - ContextManager
        model input context selection

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
        # Obtain schemas through ToolRegistry
        # ----------------------------------------------------

        tool_schemas = (
            self.tool_registry
            .get_schemas()
        )

        # ====================================================
        # Agent loop
        # ====================================================

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

            # ------------------------------------------------
            # Build current LLM context
            # ------------------------------------------------

            context = (
                self.context_manager
                .build(
                    self.history
                )
            )

            # ------------------------------------------------
            # Call model with retry policy
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Parse model output
            # ------------------------------------------------

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

                self.history.add_runtime_feedback(
                    (
                        "The previous model response "
                        "could not be parsed by the "
                        "local runtime: "
                        f"{exc}. "
                        "Please try again."
                    )
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

            # ------------------------------------------------
            # Save assistant message
            # ------------------------------------------------

            self.history.add_assistant_message(
                parsed.assistant_message
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

                # --------------------------------------------
                # Agent accepts completion
                # --------------------------------------------

                if decision.can_finish:
                    return (
                        parsed.content
                        or (
                            "Task completed "
                            "successfully."
                        )
                    )

                # --------------------------------------------
                # Agent rejects premature completion
                # --------------------------------------------

                print()

                print(
                    "[Runtime Guard] "
                    + decision.reason
                )

                self.history.add_runtime_feedback(
                    decision.feedback
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

            # ------------------------------------------------
            # Runtime termination check
            # ------------------------------------------------

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
                    runtime_decision.feedback
                )

        # ====================================================
        # Maximum-step termination
        # ====================================================

        raise RuntimeError(
            self.termination_policy
            .max_steps_error()
        )

    # ========================================================
    # Tool-call handling
    # ========================================================

    def _handle_tool_call(
        self,
        tool_call,
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
        # Local tool execution
        # ----------------------------------------------------

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
            # ToolRegistry already handles ordinary
            # tool errors.
            #
            # This extra boundary prevents an unexpected
            # registry bug from crashing the loop without
            # producing a structured observation.

            tool_result = (
                self.error_handler
                .build_tool_error(
                    error=str(exc),
                    tool_name=(
                        tool_name
                    ),
                )
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

        self._print_tool_result(
            tool_result
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
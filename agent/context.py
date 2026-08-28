from .history import ConversationHistory
from .working_memory import WorkingMemory


class ContextManager:
    """
    Build the message context sent to the language model.

    ConversationHistory stores the complete history, while this class
    decides which part of that history should be included in the next
    model call.

    Current strategy:

    1. Always keep the system prompt.
    2. Always keep the original user task.
    3. Inject deterministic runtime WorkingMemory when available.
    4. Keep only the most recent remaining messages when history grows.
    5. Never start the retained tail with an orphaned tool message.

    This is intentionally a simple message-count based strategy.

    Token-aware compression can be added later without changing
    CodingAgent's interface.
    """

    def __init__(
        self,
        max_context_messages: int = 40,
    ) -> None:
        if max_context_messages < 2:
            raise ValueError(
                "max_context_messages must "
                "be at least 2."
            )

        self.max_context_messages = (
            max_context_messages
        )

    # ========================================================
    # Build context
    # ========================================================

    def build(
        self,
        history: ConversationHistory,
        working_memory: WorkingMemory | None = None,
    ) -> list[dict]:
        messages = (
            history.get_messages()
        )

        if not messages:
            return []

        system_message = (
            self._find_system_message(
                messages
            )
        )

        task_index = (
            self._find_original_task_index(
                messages
            )
        )

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        if (
            system_message is None
            or task_index is None
        ):
            return self._recent_slice(
                messages
            )

        # ----------------------------------------------------
        # Keep original task permanently
        # ----------------------------------------------------

        task_message = (
            messages[task_index]
        )

        tail = (
            messages[
                task_index + 1 :
            ]
        )

        # max_context_messages counts
        # non-system messages here.
        #
        # One position is reserved for
        # the original user task.
        tail_budget = max(
            0,
            self.max_context_messages
            - 1,
        )

        # ----------------------------------------------------
        # Truncate old context
        # ----------------------------------------------------

        if len(tail) > tail_budget:
            tail = tail[
                -tail_budget:
            ]

            # If truncation starts in the middle of:
            #
            # assistant(tool_call)
            # tool(result)
            #
            # do not leave an orphaned tool message
            # without its corresponding assistant call.
            while (
                tail
                and tail[0].get("role")
                == "tool"
            ):
                tail.pop(0)

        selected = [
            system_message,
        ]

        if working_memory is not None:
            selected.append(
                working_memory.to_context_message()
            )

        selected.extend(
            [
                task_message,
                *tail,
            ]
        )

        return selected

    # ========================================================
    # Fallback context
    # ========================================================

    def _recent_slice(
        self,
        messages: list[dict],
    ) -> list[dict]:
        """
        Fallback strategy for an unusual history layout.
        """

        if (
            len(messages)
            <= self.max_context_messages
        ):
            return messages

        selected = messages[
            -self.max_context_messages:
        ]

        while (
            selected
            and selected[0].get("role")
            == "tool"
        ):
            selected.pop(0)

        return selected

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _find_system_message(
        messages: list[dict],
    ) -> dict | None:
        for message in messages:
            if (
                message.get("role")
                == "system"
            ):
                return message

        return None

    @staticmethod
    def _find_original_task_index(
        messages: list[dict],
    ) -> int | None:
        for index, message in enumerate(
            messages
        ):
            if (
                message.get("role")
                == "user"
            ):
                return index

        return None
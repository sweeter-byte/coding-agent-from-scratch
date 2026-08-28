import json

from dataclasses import dataclass

from typing import Any


# ============================================================
# Parser exceptions
# ============================================================

class ModelOutputError(
    RuntimeError
):
    """
    Raised when the model response cannot be converted into
    the internal response format required by CodingAgent.
    """


# ============================================================
# Internal response structures
# ============================================================

@dataclass(frozen=True)
class ParsedToolCall:
    id: str
    name: str
    raw_arguments: str

    arguments: dict | None

    error: str | None = None

    @property
    def is_valid(
        self,
    ) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ParsedModelResponse:
    content: str

    assistant_message: dict

    tool_calls: list[
        ParsedToolCall
    ]


# ============================================================
# Response parser
# ============================================================

class ResponseParser:
    """
    Convert an OpenAI-compatible SDK response into the agent's
    own plain Python data structures.

    CodingAgent therefore does not need to directly manipulate:

        response.choices[0].message

    or manually parse tool-call JSON.
    """

    # ========================================================
    # Public parse
    # ========================================================

    def parse(
        self,
        response: Any,
    ) -> ParsedModelResponse:

        message = (
            self._extract_message(
                response
            )
        )

        content = getattr(
            message,
            "content",
            None,
        ) or ""

        raw_tool_calls = getattr(
            message,
            "tool_calls",
            None,
        ) or []

        assistant_message: dict = {
            "role": "assistant",
            "content": content,
        }

        parsed_tool_calls: list[
            ParsedToolCall
        ] = []

        # ----------------------------------------------------
        # Preserve tool calls in conversation history
        # ----------------------------------------------------

        if raw_tool_calls:
            assistant_message[
                "tool_calls"
            ] = []

        for tool_call in raw_tool_calls:

            parsed_tool_call = (
                self._parse_tool_call(
                    tool_call
                )
            )

            parsed_tool_calls.append(
                parsed_tool_call
            )

            assistant_message[
                "tool_calls"
            ].append(
                {
                    "id": (
                        parsed_tool_call.id
                    ),
                    "type": "function",
                    "function": {
                        "name": (
                            parsed_tool_call.name
                        ),
                        "arguments": (
                            parsed_tool_call
                            .raw_arguments
                        ),
                    },
                }
            )

        return ParsedModelResponse(
            content=content,
            assistant_message=(
                assistant_message
            ),
            tool_calls=(
                parsed_tool_calls
            ),
        )

    # ========================================================
    # Extract SDK message
    # ========================================================

    @staticmethod
    def _extract_message(
        response: Any,
    ) -> Any:

        choices = getattr(
            response,
            "choices",
            None,
        )

        if not choices:
            raise ModelOutputError(
                "Model response contains no choices."
            )

        message = getattr(
            choices[0],
            "message",
            None,
        )

        if message is None:
            raise ModelOutputError(
                "Model response contains "
                "no assistant message."
            )

        return message

    # ========================================================
    # Parse tool call
    # ========================================================

    @staticmethod
    def _parse_tool_call(
        tool_call: Any,
    ) -> ParsedToolCall:

        call_id = getattr(
            tool_call,
            "id",
            None,
        )

        function = getattr(
            tool_call,
            "function",
            None,
        )

        if (
            not call_id
            or function is None
        ):
            raise ModelOutputError(
                "Malformed tool call: "
                "missing id or function."
            )

        name = getattr(
            function,
            "name",
            None,
        )

        raw_arguments = getattr(
            function,
            "arguments",
            None,
        )

        if not name:
            raise ModelOutputError(
                "Malformed tool call: "
                "missing function name."
            )

        if raw_arguments is None:
            raw_arguments = "{}"

        if not isinstance(
            raw_arguments,
            str,
        ):
            raw_arguments = str(
                raw_arguments
            )

        # ----------------------------------------------------
        # Parse JSON arguments
        # ----------------------------------------------------

        try:
            arguments = json.loads(
                raw_arguments
            )

        except json.JSONDecodeError as exc:
            return ParsedToolCall(
                id=call_id,
                name=name,
                raw_arguments=(
                    raw_arguments
                ),
                arguments=None,
                error=(
                    "Invalid JSON arguments "
                    "generated by the model: "
                    + str(exc)
                ),
            )

        # ----------------------------------------------------
        # Tool arguments must be a JSON object
        # ----------------------------------------------------

        if not isinstance(
            arguments,
            dict,
        ):
            return ParsedToolCall(
                id=call_id,
                name=name,
                raw_arguments=(
                    raw_arguments
                ),
                arguments=None,
                error=(
                    "Tool arguments must decode "
                    "to a JSON object."
                ),
            )

        return ParsedToolCall(
            id=call_id,
            name=name,
            raw_arguments=(
                raw_arguments
            ),
            arguments=arguments,
        )
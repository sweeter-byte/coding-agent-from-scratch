import json
import time

from collections.abc import Callable

from typing import TypeVar


T = TypeVar("T")


class ErrorHandler:
    """
    Centralize recoverable runtime error handling.

    First version responsibilities:

    1. Retry failed model API calls a limited number of times.
    2. Convert tool/parser failures into structured JSON observations.
    3. Safely parse tool execution results returned by local tools.

    More precise exception classification can be added later without
    changing CodingAgent's main loop.
    """

    def __init__(
        self,
        max_model_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:

        if max_model_retries < 0:
            raise ValueError(
                "max_model_retries cannot "
                "be negative."
            )

        if retry_delay_seconds < 0:
            raise ValueError(
                "retry_delay_seconds cannot "
                "be negative."
            )

        self.max_model_retries = (
            max_model_retries
        )

        self.retry_delay_seconds = (
            retry_delay_seconds
        )

    # ========================================================
    # Model API retry
    # ========================================================

    def run_model_call(
        self,
        operation: Callable[[], T],
    ) -> T:
        """
        Execute one model API operation with bounded retries.

        max_model_retries=2 means at most three total attempts:

        initial request
        + retry 1
        + retry 2
        """

        last_error: Exception | None = (
            None
        )

        total_attempts = (
            self.max_model_retries
            + 1
        )

        for attempt in range(
            1,
            total_attempts + 1,
        ):
            try:
                return operation()

            except Exception as exc:
                last_error = exc

                if (
                    attempt
                    >= total_attempts
                ):
                    break

                print()
                print(
                    "[Model Error] "
                    f"Attempt "
                    f"{attempt}/{total_attempts} "
                    f"failed: {exc}"
                )

                print(
                    "Retrying model request..."
                )

                delay = (
                    self.retry_delay_seconds
                    * attempt
                )

                if delay > 0:
                    time.sleep(
                        delay
                    )

        raise RuntimeError(
            "Model request failed after "
            f"{total_attempts} attempt(s): "
            f"{last_error}"
        ) from last_error

    # ========================================================
    # Structured tool error
    # ========================================================

    @staticmethod
    def build_tool_error(
        error: str,
        tool_name: str | None = None,
    ) -> str:

        payload = {
            "ok": False,
            "error": error,
        }

        if tool_name:
            payload[
                "tool"
            ] = tool_name

        return json.dumps(
            payload,
            ensure_ascii=False,
        )

    # ========================================================
    # Tool result parser
    # ========================================================

    @staticmethod
    def parse_tool_result(
        tool_result: str,
    ) -> dict:
        """
        Local tools are expected to return JSON strings.

        If a tool violates that contract, convert it into a
        structured failure instead of crashing the main loop.
        """

        try:
            result = json.loads(
                tool_result
            )

        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": (
                    "Tool returned invalid JSON."
                ),
                "raw_result": (
                    tool_result[:2000]
                ),
            }

        if not isinstance(
            result,
            dict,
        ):
            return {
                "ok": False,
                "error": (
                    "Tool result must be "
                    "a JSON object."
                ),
                "raw_result": (
                    tool_result[:2000]
                ),
            }

        # ----------------------------------------------------
        # Tool result contract validation
        # ----------------------------------------------------

        if "ok" not in result:
            result["ok"] = False

            result.setdefault(
                "error",
                (
                    "Tool result does not "
                    "contain an 'ok' field."
                ),
            )

        return result
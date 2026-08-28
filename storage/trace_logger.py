from __future__ import annotations

import json
import threading
import uuid

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from security import SensitiveDataPolicy


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_TRACE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "traces"
)


# ============================================================
# Trace Logger
# ============================================================

class TraceLogger:
    """
    Append-only JSONL logger for CodingAgent runtime events.

    Trace logs are deliberately separated from ConversationHistory.

    ConversationHistory:
        information used to continue the agent conversation

    TraceLogger:
        information used for debugging, observability,
        performance analysis and auditing

    Example log file:

        logs/traces/
        └── run_20260828_103015_a12b34cd.jsonl
    """

    # Backward-compatible alias; detection is centralized in
    # SensitiveDataPolicy.
    SENSITIVE_KEYS = SensitiveDataPolicy.SENSITIVE_KEYS

    def __init__(
        self,
        directory: str | Path | None = None,
        run_id: str | None = None,
        max_string_length: int = 10000,
        sensitive_data_policy: SensitiveDataPolicy | None = None,
    ) -> None:

        if directory is None:
            self.directory = (
                DEFAULT_TRACE_DIR
            )
        else:
            self.directory = Path(
                directory
            )

            if not self.directory.is_absolute():
                self.directory = (
                    PROJECT_ROOT
                    / self.directory
                )

        self.directory = (
            self.directory.resolve()
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        if max_string_length <= 0:
            raise ValueError(
                "max_string_length must "
                "be greater than 0."
            )

        self.max_string_length = (
            max_string_length
        )

        self.sensitive_data_policy = (
            sensitive_data_policy
            or SensitiveDataPolicy()
        )

        self.run_id = (
            run_id
            or self._generate_run_id()
        )

        self.path = (
            self.directory
            / f"run_{self.run_id}.jsonl"
        )

        # Protect append operations in case future code
        # executes tools concurrently.
        self._lock = (
            threading.Lock()
        )

    # ========================================================
    # Generic event logger
    # ========================================================

    def log(
        self,
        event: str,
        step: int | None = None,
        **data: Any,
    ) -> None:
        """
        Append one structured event to the JSONL trace.
        """

        if not event:
            raise ValueError(
                "event cannot be empty."
            )

        record = {
            "timestamp": (
                self._utc_now()
            ),
            "run_id": self.run_id,
            "event": event,
        }

        if step is not None:
            record[
                "step"
            ] = step

        if data:
            record[
                "data"
            ] = (
                self._sanitize(
                    data
                )
            )

        line = json.dumps(
            record,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        with self._lock:
            with self.path.open(
                "a",
                encoding="utf-8",
            ) as file:
                file.write(
                    line
                )

                file.write(
                    "\n"
                )

                # Trace data is debugging information.
                # Flush immediately so a later crash does not
                # lose the most recent event.
                file.flush()

    # ========================================================
    # Agent lifecycle
    # ========================================================

    def log_agent_start(
        self,
        task: str,
        model: str,
        workspace: str | Path,
    ) -> None:

        self.log(
            "agent_start",
            task=task,
            model=model,
            workspace=str(
                workspace
            ),
        )

    def log_session_resume(
        self,
        restored_step: int,
        next_step: int,
        previous_status: str | None,
    ) -> None:
        """
        Record that an existing persisted session is being resumed.
        """

        self.log(
            "session_resume",
            step=restored_step,
            restored_step=(
                restored_step
            ),
            next_step=next_step,
            previous_status=(
                previous_status
            ),
        )

    def log_agent_step(
        self,
        step: int,
    ) -> None:

        self.log(
            "agent_step",
            step=step,
        )

    def log_agent_finish(
        self,
        step: int,
        result: str,
    ) -> None:

        self.log(
            "agent_finish",
            step=step,
            result=result,
        )

    def log_agent_stop(
        self,
        step: int,
        reason: str,
    ) -> None:

        self.log(
            "agent_stop",
            step=step,
            reason=reason,
        )

    # ========================================================
    # Model events
    # ========================================================

    def log_model_call(
        self,
        step: int,
        model: str,
        message_count: int,
        tool_count: int,
    ) -> None:

        self.log(
            "model_call",
            step=step,
            model=model,
            message_count=(
                message_count
            ),
            tool_count=tool_count,
        )

    def log_model_response(
        self,
        step: int,
        content: str,
        tool_call_count: int,
        usage: Any | None = None,
        duration_ms: float | None = None,
    ) -> None:

        payload: dict[str, Any] = {
            "content": content,
            "tool_call_count": (
                tool_call_count
            ),
        }

        if usage is not None:
            payload[
                "usage"
            ] = usage

        if duration_ms is not None:
            payload[
                "duration_ms"
            ] = duration_ms

        self.log(
            "model_response",
            step=step,
            **payload,
        )

    # ========================================================
    # Tool events
    # ========================================================

    def log_tool_call(
        self,
        step: int,
        tool_name: str,
        arguments: dict,
        tool_call_id: str | None = None,
    ) -> None:

        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "arguments": arguments,
        }

        if tool_call_id is not None:
            payload[
                "tool_call_id"
            ] = tool_call_id

        self.log(
            "tool_call",
            step=step,
            **payload,
        )

    def log_tool_result(
        self,
        step: int,
        tool_name: str,
        result: Any,
        ok: bool | None = None,
        duration_ms: float | None = None,
        tool_call_id: str | None = None,
    ) -> None:

        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "result": result,
        }

        if ok is not None:
            payload[
                "ok"
            ] = ok

        if duration_ms is not None:
            payload[
                "duration_ms"
            ] = duration_ms

        if tool_call_id is not None:
            payload[
                "tool_call_id"
            ] = tool_call_id

        self.log(
            "tool_result",
            step=step,
            **payload,
        )

    # ========================================================
    # Error events
    # ========================================================

    def log_error(
        self,
        error: str,
        source: str,
        step: int | None = None,
        recoverable: bool = True,
    ) -> None:

        self.log(
            "error",
            step=step,
            source=source,
            error=error,
            recoverable=(
                recoverable
            ),
        )

    # ========================================================
    # Runtime feedback
    # ========================================================

    def log_runtime_feedback(
        self,
        step: int,
        feedback: str,
        reason: str | None = None,
    ) -> None:

        payload: dict[str, Any] = {
            "feedback": feedback,
        }

        if reason is not None:
            payload[
                "reason"
            ] = reason

        self.log(
            "runtime_feedback",
            step=step,
            **payload,
        )

    # ========================================================
    # Get current trace path
    # ========================================================

    def get_log_path(
        self,
    ) -> Path:
        return self.path

    # ========================================================
    # Sanitize data
    # ========================================================

    def _sanitize(
        self,
        value: Any,
        key: str | None = None,
    ) -> Any:
        """
        Convert arbitrary runtime objects into JSON-safe values,
        redact sensitive fields and prevent individual values from
        making the trace file excessively large.
        """

        # ----------------------------------------------------
        # Redact secret-looking fields
        # ----------------------------------------------------

        if (
            key is not None
            and self.sensitive_data_policy.is_sensitive_key(
                key
            )
        ):
            return "[REDACTED]"

        # ----------------------------------------------------
        # Primitive values
        # ----------------------------------------------------

        if value is None:
            return None

        if isinstance(
            value,
            bool,
        ):
            return value

        if isinstance(
            value,
            int,
        ):
            return value

        if isinstance(
            value,
            float,
        ):
            return value

        # ----------------------------------------------------
        # Strings
        # ----------------------------------------------------

        if isinstance(
            value,
            str,
        ):
            return self._truncate_string(
                self.sensitive_data_policy.redact_text(
                    value
                )
            )

        # ----------------------------------------------------
        # Path
        # ----------------------------------------------------

        if isinstance(
            value,
            Path,
        ):
            return self._truncate_string(
                self.sensitive_data_policy.redact_text(
                    str(value)
                )
            )

        # ----------------------------------------------------
        # Enum
        # ----------------------------------------------------

        if isinstance(
            value,
            Enum,
        ):
            return self._sanitize(
                value.value,
                key=key,
            )

        # ----------------------------------------------------
        # Dataclass
        # ----------------------------------------------------

        if is_dataclass(
            value
        ):
            return self._sanitize(
                asdict(
                    value
                ),
                key=key,
            )

        # ----------------------------------------------------
        # Dictionary
        # ----------------------------------------------------

        if isinstance(
            value,
            dict,
        ):
            result = {}

            for item_key, item_value in (
                value.items()
            ):
                item_key_str = str(
                    item_key
                )

                result[
                    item_key_str
                ] = self._sanitize(
                    item_value,
                    key=item_key_str,
                )

            return result

        # ----------------------------------------------------
        # Sequence
        # ----------------------------------------------------

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            return [
                self._sanitize(
                    item
                )
                for item in value
            ]

        # ----------------------------------------------------
        # OpenAI / SDK style objects
        # ----------------------------------------------------

        model_dump = getattr(
            value,
            "model_dump",
            None,
        )

        if callable(
            model_dump
        ):
            try:
                return self._sanitize(
                    model_dump()
                )
            except Exception:
                pass

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        return self._truncate_string(
            self.sensitive_data_policy.redact_text(
                str(value)
            )
        )

    # ========================================================
    # Sensitive-key detection
    # ========================================================

    @classmethod
    def _is_sensitive_key(
        cls,
        key: str,
    ) -> bool:
        return SensitiveDataPolicy.is_sensitive_key(
            key
        )


    # ========================================================
    # String truncation
    # ========================================================

    def _truncate_string(
        self,
        value: str,
    ) -> str:

        if (
            len(value)
            <= self.max_string_length
        ):
            return value

        removed = (
            len(value)
            - self.max_string_length
        )

        return (
            value[
                : self.max_string_length
            ]
            + "\n"
            + (
                "[TRUNCATED: "
                f"{removed} characters omitted]"
            )
        )

    # ========================================================
    # Run ID
    # ========================================================

    @staticmethod
    def _generate_run_id() -> str:

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%d_%H%M%S"
            )
        )

        random_part = (
            uuid.uuid4()
            .hex[:8]
        )

        return (
            f"{timestamp}_"
            f"{random_part}"
        )

    # ========================================================
    # Time
    # ========================================================

    @staticmethod
    def _utc_now() -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
        )
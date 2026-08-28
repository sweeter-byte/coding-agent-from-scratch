from __future__ import annotations

import json
import re
import uuid

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_SESSION_DIR = (
    PROJECT_ROOT
    / "data"
    / "sessions"
)


# ============================================================
# Constants
# ============================================================

SESSION_SCHEMA_VERSION = 1

SESSION_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]+$"
)


# ============================================================
# Protocols
# ============================================================

class HistoryLike(Protocol):
    """
    Minimal interface required by SessionStore.

    ConversationHistory already satisfies this protocol.

    Using Protocol avoids importing agent.history here,
    which keeps storage independent from the agent package
    and prevents circular dependencies.
    """

    def get_messages(self) -> list[dict]:
        ...

    def restore(
        self,
        messages: list[dict],
    ) -> None:
        ...


# ============================================================
# Session Store
# ============================================================

class SessionStore:
    """
    Persistent storage for agent conversation sessions.

    One session is stored as one JSON file.

    Example:

        data/
        └── sessions/
            ├── 20260828_103015_a12b34cd.json
            └── 20260828_110402_f0e91a22.json

    SessionStore stores durable conversation data.

    It is intentionally separate from TraceLogger:

    - SessionStore:
        data required to restore an agent conversation

    - TraceLogger:
        runtime/debugging/observability events
    """

    def __init__(
        self,
        directory: str | Path | None = None,
    ) -> None:

        if directory is None:
            self.directory = (
                DEFAULT_SESSION_DIR
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

    # ========================================================
    # Session creation
    # ========================================================

    def create_session(
        self,
        metadata: dict | None = None,
    ) -> str:
        """
        Create a new empty session and return its session ID.
        """

        session_id = (
            self._generate_session_id()
        )

        self.save(
            session_id=session_id,
            messages=[],
            metadata=metadata,
            state={},
        )

        return session_id

    # ========================================================
    # Save
    # ========================================================

    def save(
        self,
        session_id: str,
        messages: list[dict],
        metadata: dict | None = None,
        state: Any | None = None,
    ) -> None:
        """
        Persist one complete session.

        Parameters
        ----------
        session_id:
            Unique local session identifier.

        messages:
            Complete conversation history.

        metadata:
            Optional descriptive information, for example:

                {
                    "task": "...",
                    "model": "qwen3.7-plus",
                    "workspace": "workspace"
                }

        state:
            Optional AgentState or plain dictionary.
        """

        session_id = (
            self._validate_session_id(
                session_id
            )
        )

        if not isinstance(
            messages,
            list,
        ):
            raise TypeError(
                "messages must be a list."
            )

        for message in messages:
            if not isinstance(
                message,
                dict,
            ):
                raise TypeError(
                    "Each message must be "
                    "a dictionary."
                )

        path = self._session_path(
            session_id
        )

        now = self._utc_now()

        # ----------------------------------------------------
        # Preserve previous metadata and creation time
        # ----------------------------------------------------

        existing: dict | None = None

        if path.exists():
            try:
                existing = (
                    self._read_json(
                        path
                    )
                )
            except Exception:
                # If an existing file is damaged,
                # saving a new valid snapshot is still allowed.
                existing = None

        created_at = now

        old_metadata: dict = {}

        old_state: Any = {}

        if existing:
            created_at = (
                existing.get(
                    "created_at",
                    now,
                )
            )

            if isinstance(
                existing.get("metadata"),
                dict,
            ):
                old_metadata = (
                    existing["metadata"]
                )

            if "state" in existing:
                old_state = (
                    existing["state"]
                )

        # ----------------------------------------------------
        # Merge metadata
        # ----------------------------------------------------

        merged_metadata = dict(
            old_metadata
        )

        if metadata is not None:
            if not isinstance(
                metadata,
                dict,
            ):
                raise TypeError(
                    "metadata must be "
                    "a dictionary."
                )

            merged_metadata.update(
                metadata
            )

        # ----------------------------------------------------
        # Preserve state when no new state is supplied
        # ----------------------------------------------------

        if state is None:
            stored_state = old_state
        else:
            stored_state = (
                self._to_jsonable(
                    state
                )
            )

        # ----------------------------------------------------
        # Build session snapshot
        # ----------------------------------------------------

        payload = {
            "schema_version": (
                SESSION_SCHEMA_VERSION
            ),
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": now,
            "metadata": (
                self._to_jsonable(
                    merged_metadata
                )
            ),
            "state": stored_state,
            "messages": (
                self._to_jsonable(
                    messages
                )
            ),
        }

        # ----------------------------------------------------
        # Atomic persistence
        # ----------------------------------------------------

        self._write_json_atomic(
            path=path,
            payload=payload,
        )

    # ========================================================
    # Save ConversationHistory directly
    # ========================================================

    def save_history(
        self,
        session_id: str,
        history: HistoryLike,
        metadata: dict | None = None,
        state: Any | None = None,
    ) -> None:
        """
        Save a ConversationHistory-compatible object.

        Example:

            store.save_history(
                session_id,
                agent.history,
                state=agent.state,
            )
        """

        messages = (
            history.get_messages()
        )

        self.save(
            session_id=session_id,
            messages=messages,
            metadata=metadata,
            state=state,
        )

    # ========================================================
    # Load
    # ========================================================

    def load(
        self,
        session_id: str,
    ) -> dict:
        """
        Load the full stored session.
        """

        session_id = (
            self._validate_session_id(
                session_id
            )
        )

        path = self._session_path(
            session_id
        )

        if not path.exists():
            raise FileNotFoundError(
                "Session does not exist: "
                f"{session_id}"
            )

        data = self._read_json(
            path
        )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Invalid session file: "
                "root value must be an object."
            )

        if (
            data.get("session_id")
            != session_id
        ):
            raise ValueError(
                "Session file ID does not "
                "match requested session ID."
            )

        return data

    # ========================================================
    # Load messages only
    # ========================================================

    def load_messages(
        self,
        session_id: str,
    ) -> list[dict]:
        """
        Load only the conversation history.
        """

        data = self.load(
            session_id
        )

        messages = data.get(
            "messages",
            [],
        )

        if not isinstance(
            messages,
            list,
        ):
            raise ValueError(
                "Invalid session file: "
                "'messages' must be a list."
            )

        return messages

    # ========================================================
    # Restore ConversationHistory
    # ========================================================

    def restore_history(
        self,
        session_id: str,
        history: HistoryLike,
    ) -> dict:
        """
        Restore persisted messages into ConversationHistory.

        Returns the complete stored session so callers can also
        inspect metadata and persisted AgentState.

        Example:

            session = store.restore_history(
                session_id,
                agent.history,
            )
        """

        data = self.load(
            session_id
        )

        messages = data.get(
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

        history.restore(
            messages
        )

        return data

    # ========================================================
    # Existence
    # ========================================================

    def exists(
        self,
        session_id: str,
    ) -> bool:

        session_id = (
            self._validate_session_id(
                session_id
            )
        )

        return (
            self._session_path(
                session_id
            )
            .exists()
        )

    # ========================================================
    # Delete session
    # ========================================================

    def delete(
        self,
        session_id: str,
    ) -> bool:
        """
        Delete a stored session.

        Returns True if a file was deleted,
        False if it did not exist.
        """

        session_id = (
            self._validate_session_id(
                session_id
            )
        )

        path = self._session_path(
            session_id
        )

        if not path.exists():
            return False

        path.unlink()

        return True

    # ========================================================
    # List sessions
    # ========================================================

    def list_sessions(
        self,
    ) -> list[dict]:
        """
        Return lightweight metadata for stored sessions.

        The full message contents are intentionally omitted so that
        a future UI can list sessions without loading every message.
        """

        sessions: list[dict] = []

        for path in (
            self.directory
            .glob("*.json")
        ):
            try:
                data = (
                    self._read_json(
                        path
                    )
                )

                messages = data.get(
                    "messages",
                    [],
                )

                message_count = (
                    len(messages)
                    if isinstance(
                        messages,
                        list,
                    )
                    else 0
                )

                sessions.append(
                    {
                        "session_id": (
                            data.get(
                                "session_id",
                                path.stem,
                            )
                        ),
                        "created_at": (
                            data.get(
                                "created_at"
                            )
                        ),
                        "updated_at": (
                            data.get(
                                "updated_at"
                            )
                        ),
                        "message_count": (
                            message_count
                        ),
                        "metadata": (
                            data.get(
                                "metadata",
                                {},
                            )
                        ),
                    }
                )

            except Exception as exc:
                # Do not let one damaged file prevent all
                # valid sessions from being listed.
                sessions.append(
                    {
                        "session_id": (
                            path.stem
                        ),
                        "error": str(exc),
                    }
                )

        # ISO-8601 timestamps sort correctly
        # as ordinary strings.
        sessions.sort(
            key=lambda item: (
                item.get(
                    "updated_at",
                    "",
                )
                or ""
            ),
            reverse=True,
        )

        return sessions

    # ========================================================
    # Session path
    # ========================================================

    def _session_path(
        self,
        session_id: str,
    ) -> Path:

        return (
            self.directory
            / f"{session_id}.json"
        )

    # ========================================================
    # Session ID generation
    # ========================================================

    @staticmethod
    def _generate_session_id() -> str:

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
    # Session ID validation
    # ========================================================

    @staticmethod
    def _validate_session_id(
        session_id: str,
    ) -> str:

        if not isinstance(
            session_id,
            str,
        ):
            raise TypeError(
                "session_id must be a string."
            )

        session_id = (
            session_id.strip()
        )

        if not session_id:
            raise ValueError(
                "session_id cannot be empty."
            )

        if not SESSION_ID_PATTERN.fullmatch(
            session_id
        ):
            raise ValueError(
                "Invalid session_id. "
                "Only letters, digits, '-' "
                "and '_' are allowed."
            )

        return session_id

    # ========================================================
    # Atomic JSON write
    # ========================================================

    @staticmethod
    def _write_json_atomic(
        path: Path,
        payload: dict,
    ) -> None:
        """
        Write through a temporary file and then replace the target.

        This prevents a process crash during json.dump() from leaving
        the main session file half-written.
        """

        temp_path = path.with_name(
            path.name
            + ".tmp-"
            + uuid.uuid4().hex
        )

        try:
            with temp_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

                file.write(
                    "\n"
                )

                file.flush()

            temp_path.replace(
                path
            )

        finally:
            if temp_path.exists():
                temp_path.unlink()

    # ========================================================
    # JSON reader
    # ========================================================

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict:

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(
                file
            )

    # ========================================================
    # UTC timestamp
    # ========================================================

    @staticmethod
    def _utc_now() -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
        )

    # ========================================================
    # Convert runtime objects to JSON-compatible data
    # ========================================================

    @classmethod
    def _to_jsonable(
        cls,
        value: Any,
    ) -> Any:

        if value is None:
            return None

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return value

        if isinstance(
            value,
            Path,
        ):
            return str(
                value
            )

        if isinstance(
            value,
            Enum,
        ):
            return cls._to_jsonable(
                value.value
            )

        if is_dataclass(
            value
        ):
            return cls._to_jsonable(
                asdict(
                    value
                )
            )

        if isinstance(
            value,
            dict,
        ):
            return {
                str(key): (
                    cls._to_jsonable(
                        item
                    )
                )
                for key, item
                in value.items()
            }

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            return [
                cls._to_jsonable(
                    item
                )
                for item in value
            ]

        # Fallback for simple runtime values.
        return str(
            value
        )
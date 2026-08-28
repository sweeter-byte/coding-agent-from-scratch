from __future__ import annotations

import json

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .command_tools import CommandTools
from .file_tools import FileTools

from .schemas import (
    EDIT_FILE_SCHEMA,
    LIST_FILES_SCHEMA,
    READ_FILE_SCHEMA,
    RUN_COMMAND_SCHEMA,
    SEARCH_TEXT_SCHEMA,
    WRITE_FILE_SCHEMA,
)

from .workspace import WorkspaceManager


ToolHandler = Callable[..., str]


@dataclass(frozen=True)
class ToolDefinition:
    """
    Bind one LLM-visible schema to one local Python implementation.

    Tool names are extracted from schemas during registration,
    so schema names and local handler names cannot silently drift
    through two independently maintained name tables.
    """

    name: str
    schema: dict
    handler: ToolHandler


class ToolRegistry:
    """
    Public entry point for the local tool subsystem.

    CodingAgent only needs:

        registry.get_schemas()

        registry.execute(
            name,
            arguments,
        )

    It does not need to know which concrete class
    implements each tool.
    """

    def __init__(
        self,
        workspace: str | Path,
    ) -> None:

        self.workspace = (
            WorkspaceManager(
                workspace
            )
        )

        self.file_tools = (
            FileTools(
                self.workspace
            )
        )

        self.command_tools = (
            CommandTools(
                self.workspace
            )
        )

        self._tools: dict[
            str,
            ToolDefinition,
        ] = {}

        # ----------------------------------------------------
        # Register schema + local implementation together
        # ----------------------------------------------------

        self._register(
            LIST_FILES_SCHEMA,
            self.file_tools.list_files,
        )

        self._register(
            SEARCH_TEXT_SCHEMA,
            self.file_tools.search_text,
        )

        self._register(
            READ_FILE_SCHEMA,
            self.file_tools.read_file,
        )

        self._register(
            WRITE_FILE_SCHEMA,
            self.file_tools.write_file,
        )

        self._register(
            EDIT_FILE_SCHEMA,
            self.file_tools.edit_file,
        )

        self._register(
            RUN_COMMAND_SCHEMA,
            self.command_tools.run_command,
        )

    # ========================================================
    # Schema access
    # ========================================================

    def get_schemas(
        self,
    ) -> list[dict]:
        """
        Return defensive copies of schemas exposed to the model.
        """

        return [
            deepcopy(
                definition.schema
            )
            for definition
            in self._tools.values()
        ]

    def list_tools(
        self,
    ) -> list[str]:
        """
        Return registered tool names.

        Mainly useful for unit tests and debugging.
        """

        return list(
            self._tools.keys()
        )

    # ========================================================
    # Local dispatch
    # ========================================================

    def execute(
        self,
        name: str,
        arguments: dict,
    ) -> str:
        """
        Execute one registered local tool.

        The method always returns a JSON string.
        """

        if (
            not isinstance(
                name,
                str,
            )
            or not name
        ):
            return self._error(
                "Tool name must be "
                "a non-empty string."
            )

        if not isinstance(
            arguments,
            dict,
        ):
            return self._error(
                "Tool arguments must "
                "be a dictionary.",
                tool=name,
            )

        definition = (
            self._tools.get(
                name
            )
        )

        if definition is None:
            return self._error(
                f"Unknown tool: {name}",
                tool=name,
            )

        try:
            result = (
                definition.handler(
                    **arguments
                )
            )

            if not isinstance(
                result,
                str,
            ):
                return self._error(
                    (
                        "Tool implementation violated "
                        "the runtime contract: result "
                        "must be a JSON string."
                    ),
                    tool=name,
                )

            # Validate local tool contract.
            try:
                payload = json.loads(
                    result
                )

            except json.JSONDecodeError:
                return self._error(
                    "Tool implementation "
                    "returned invalid JSON.",
                    tool=name,
                )

            if not isinstance(
                payload,
                dict,
            ):
                return self._error(
                    "Tool result JSON "
                    "must be an object.",
                    tool=name,
                )

            return result

        except TypeError as exc:
            return self._error(
                (
                    "Invalid arguments for "
                    f"tool '{name}': {exc}"
                ),
                tool=name,
            )

        except Exception as exc:
            return self._error(
                str(exc),
                tool=name,
            )

    # ========================================================
    # Registration
    # ========================================================

    def _register(
        self,
        schema: dict,
        handler: ToolHandler,
    ) -> None:

        name = self._schema_name(
            schema
        )

        if name in self._tools:
            raise ValueError(
                "Tool already registered: "
                f"{name}"
            )

        if not callable(
            handler
        ):
            raise TypeError(
                "Handler for tool "
                f"'{name}' is not callable."
            )

        self._tools[
            name
        ] = ToolDefinition(
            name=name,
            schema=deepcopy(
                schema
            ),
            handler=handler,
        )

    @staticmethod
    def _schema_name(
        schema: dict,
    ) -> str:

        try:
            name = schema[
                "function"
            ][
                "name"
            ]

        except (
            KeyError,
            TypeError,
        ) as exc:
            raise ValueError(
                "Invalid tool schema: "
                "missing function.name"
            ) from exc

        if (
            not isinstance(
                name,
                str,
            )
            or not name
        ):
            raise ValueError(
                "Invalid tool schema: "
                "function.name must be "
                "a non-empty string."
            )

        return name

    # ========================================================
    # Error response
    # ========================================================

    @staticmethod
    def _error(
        message: str,
        *,
        tool: str | None = None,
    ) -> str:

        payload = {
            "ok": False,
            "error": message,
        }

        if tool is not None:
            payload[
                "tool"
            ] = tool

        return json.dumps(
            payload,
            ensure_ascii=False,
        )

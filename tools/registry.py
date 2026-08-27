import json
from pathlib import Path

from .file_tools import FileTools
from .command_tools import CommandTools


class ToolRegistry:
    """
    Registry and dispatcher for local tools.

    CodingAgent only needs to know:

        registry.execute(
            name,
            arguments
        )

    It does not need to know how each tool
    is implemented internally.
    """

    def __init__(
        self,
        workspace: str | Path,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        # ----------------------------------------------------
        # Tool implementations
        # ----------------------------------------------------

        self.file_tools = FileTools(
            workspace=self.workspace
        )

        self.command_tools = (
            CommandTools(
                workspace=self.workspace
            )
        )

        # ----------------------------------------------------
        # Tool registry
        #
        # name -> Python callable
        # ----------------------------------------------------

        self._tools = {
            "write_file": (
                self.file_tools.write_file
            ),
            "run_command": (
                self.command_tools.run_command
            ),
        }

    # ========================================================
    # Execute tool
    # ========================================================

    def execute(
        self,
        name: str,
        arguments: dict,
    ) -> str:
        """
        Execute a registered tool.

        Example:

        execute(
            "write_file",
            {
                "path": "main.py",
                "content": "..."
            }
        )
        """

        tool = self._tools.get(
            name
        )

        if tool is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"Unknown tool: {name}"
                    ),
                },
                ensure_ascii=False,
            )

        try:
            return tool(
                **arguments
            )

        except TypeError as e:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Invalid arguments for "
                        f"tool '{name}': {e}"
                    ),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(e),
                },
                ensure_ascii=False,
            )
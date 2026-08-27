import json
from pathlib import Path


class FileTools:
    """
    File-related tools available to the coding agent.

    Current version only supports:

    - write_file

    read_file and edit_file will be added later.
    """

    def __init__(
        self,
        workspace: str | Path,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        self.workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Files created by the agent during the
        # current CodingAgent instance.
        #
        # These files may be rewritten when the
        # agent needs to fix generated code.
        self.created_files: set[Path] = set()

    # ========================================================
    # Path validation
    # ========================================================

    def _safe_path(
        self,
        relative_path: str,
    ) -> Path:
        """
        Convert a relative path into an absolute path
        inside the workspace.

        Prevent path traversal such as:

        ../../file.txt
        """

        path = Path(
            relative_path
        )

        if path.is_absolute():
            raise ValueError(
                "Absolute paths are not allowed."
            )

        target = (
            self.workspace
            / path
        ).resolve()

        try:
            target.relative_to(
                self.workspace
            )

        except ValueError:
            raise ValueError(
                "Path escapes the workspace."
            )

        return target

    # ========================================================
    # write_file
    # ========================================================

    def write_file(
        self,
        path: str,
        content: str,
    ) -> str:
        """
        Create a new file inside the workspace.

        A pre-existing user file cannot be overwritten.

        A file created by the agent during this run
        may be rewritten later to fix errors.
        """

        try:
            target = self._safe_path(
                path
            )

            # ------------------------------------------------
            # Protect pre-existing files
            # ------------------------------------------------

            if (
                target.exists()
                and target
                not in self.created_files
            ):
                return json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "Refusing to overwrite "
                            f"existing file: {path}"
                        ),
                    },
                    ensure_ascii=False,
                )

            # ------------------------------------------------
            # Ensure parent directory exists
            # ------------------------------------------------

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # ------------------------------------------------
            # Write file
            # ------------------------------------------------

            target.write_text(
                content,
                encoding="utf-8",
            )

            self.created_files.add(
                target
            )

            return json.dumps(
                {
                    "ok": True,
                    "path": path,
                    "message": (
                        "File written successfully: "
                        f"{path}"
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
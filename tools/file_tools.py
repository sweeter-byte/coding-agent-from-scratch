from __future__ import annotations

import json
from pathlib import Path

from .workspace import WorkspaceManager


class FileTools:
    """
    Local file tools available to the coding agent.

    Current operations:

    - read_file
    - write_file
    - list_files

    All paths are resolved by WorkspaceManager and therefore must stay
    inside the configured workspace.
    """

    MAX_WRITE_CHARS = 500_000
    MAX_READ_CHARS = 30_000
    MAX_READ_LINES = 500
    MAX_LIST_ENTRIES = 500

    def __init__(
        self,
        workspace: str | Path | WorkspaceManager,
    ) -> None:

        if isinstance(
            workspace,
            WorkspaceManager,
        ):
            self.workspace = workspace

        else:
            self.workspace = WorkspaceManager(
                workspace
            )

        # Files created by this FileTools instance may be rewritten
        # without setting overwrite=True.
        self._created_files: set[Path] = set()

    # ========================================================
    # read_file
    # ========================================================

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> str:
        """
        Read a UTF-8 text file from the workspace.

        Large files are bounded by both line count and character count
        so one tool result cannot consume the entire model context.
        """

        try:
            target = self.workspace.resolve_file(
                path,
                must_exist=True,
            )

            self._validate_line_range(
                start_line=start_line,
                end_line=end_line,
            )

            text = target.read_text(
                encoding="utf-8"
            )

            lines = text.splitlines(
                keepends=True
            )

            total_lines = len(lines)

            start_index = min(
                start_line - 1,
                total_lines,
            )

            if end_line is None:
                requested_end = min(
                    start_index + self.MAX_READ_LINES,
                    total_lines,
                )

            else:
                requested_end = min(
                    end_line,
                    start_index + self.MAX_READ_LINES,
                    total_lines,
                )

            selected = "".join(
                lines[start_index:requested_end]
            )

            truncated_by_chars = False

            if len(selected) > self.MAX_READ_CHARS:
                selected = selected[
                    : self.MAX_READ_CHARS
                ]

                truncated_by_chars = True

            returned_end_line = (
                requested_end
                if requested_end > 0
                else 0
            )

            truncated = (
                requested_end < total_lines
                or truncated_by_chars
            )

            return self._json(
                {
                    "ok": True,
                    "path": path,
                    "start_line": start_line,
                    "end_line": returned_end_line,
                    "total_lines": total_lines,
                    "truncated": truncated,
                    "content": selected,
                }
            )

        except UnicodeDecodeError:
            return self._json(
                {
                    "ok": False,
                    "error": (
                        "File is not valid UTF-8 text: "
                        f"{path}"
                    ),
                }
            )

        except Exception as exc:
            return self._json_error(
                exc
            )

    # ========================================================
    # write_file
    # ========================================================

    def write_file(
        self,
        path: str,
        content: str,
        overwrite: bool = False,
    ) -> str:
        """
        Write a UTF-8 text file inside the workspace.

        Safety rule:

        - a file created during this FileTools instance may be rewritten;
        - a pre-existing file requires overwrite=True.

        This preserves a safe default while still allowing explicit
        modification of existing workspace files.
        """

        try:
            if not isinstance(
                content,
                str,
            ):
                raise TypeError(
                    "content must be a string."
                )

            if len(content) > self.MAX_WRITE_CHARS:
                raise ValueError(
                    "File content is too large. "
                    f"Maximum size is "
                    f"{self.MAX_WRITE_CHARS} characters."
                )

            if not isinstance(
                overwrite,
                bool,
            ):
                raise TypeError(
                    "overwrite must be a boolean."
                )

            target = self.workspace.resolve_file(
                path
            )

            existed_before = target.exists()

            if (
                existed_before
                and target not in self._created_files
                and not overwrite
            ):
                return self._json(
                    {
                        "ok": False,
                        "error": (
                            "Refusing to overwrite a "
                            "pre-existing file without "
                            f"overwrite=true: {path}"
                        ),
                    }
                )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                content,
                encoding="utf-8",
            )

            self._created_files.add(
                target
            )

            return self._json(
                {
                    "ok": True,
                    "path": path,
                    "bytes_written": len(
                        content.encode(
                            "utf-8"
                        )
                    ),
                    "overwrote_existing": existed_before,
                    "message": (
                        "File written successfully: "
                        f"{path}"
                    ),
                }
            )

        except Exception as exc:
            return self._json_error(
                exc
            )

    # ========================================================
    # list_files
    # ========================================================

    def list_files(
        self,
        path: str = ".",
        recursive: bool = True,
        max_entries: int = 200,
    ) -> str:
        """
        List files/directories under a workspace directory.

        Symlinks resolving outside the workspace are skipped.
        """

        try:
            if not isinstance(
                recursive,
                bool,
            ):
                raise TypeError(
                    "recursive must be a boolean."
                )

            if (
                isinstance(
                    max_entries,
                    bool,
                )
                or not isinstance(
                    max_entries,
                    int,
                )
            ):
                raise TypeError(
                    "max_entries must be an integer."
                )

            max_entries = max(
                1,
                min(
                    max_entries,
                    self.MAX_LIST_ENTRIES,
                ),
            )

            directory = (
                self.workspace
                .resolve_directory(
                    path,
                    must_exist=True,
                )
            )

            iterator = (
                directory.rglob("*")
                if recursive
                else directory.iterdir()
            )

            entries: list[dict] = []

            truncated = False

            for candidate in sorted(
                iterator,
                key=lambda item: (
                    item.as_posix()
                ),
            ):
                try:
                    resolved = (
                        candidate.resolve()
                    )

                    if not self.workspace.contains(
                        resolved
                    ):
                        continue

                    relative = (
                        self.workspace
                        .relative_path(
                            resolved
                        )
                    )

                except (
                    OSError,
                    ValueError,
                ):
                    continue

                entry_type = (
                    "directory"
                    if resolved.is_dir()
                    else "file"
                    if resolved.is_file()
                    else "other"
                )

                entry = {
                    "path": relative,
                    "type": entry_type,
                }

                if resolved.is_file():
                    try:
                        entry[
                            "size_bytes"
                        ] = (
                            resolved
                            .stat()
                            .st_size
                        )

                    except OSError:
                        pass

                entries.append(
                    entry
                )

                if (
                    len(entries)
                    >= max_entries
                ):
                    truncated = True
                    break

            return self._json(
                {
                    "ok": True,
                    "path": path,
                    "recursive": recursive,
                    "entries": entries,
                    "count": len(entries),
                    "truncated": truncated,
                }
            )

        except Exception as exc:
            return self._json_error(
                exc
            )

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _validate_line_range(
        start_line: int,
        end_line: int | None,
    ) -> None:

        if (
            isinstance(
                start_line,
                bool,
            )
            or not isinstance(
                start_line,
                int,
            )
            or start_line < 1
        ):
            raise ValueError(
                "start_line must be "
                "an integer >= 1."
            )

        if end_line is not None:
            if (
                isinstance(
                    end_line,
                    bool,
                )
                or not isinstance(
                    end_line,
                    int,
                )
                or end_line < start_line
            ):
                raise ValueError(
                    "end_line must be an "
                    "integer >= start_line."
                )

    @staticmethod
    def _json(
        payload: dict,
    ) -> str:

        return json.dumps(
            payload,
            ensure_ascii=False,
        )

    @classmethod
    def _json_error(
        cls,
        exc: Exception,
    ) -> str:

        return cls._json(
            {
                "ok": False,
                "error": str(exc),
            }
        )
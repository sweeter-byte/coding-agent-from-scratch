from __future__ import annotations

import json
import os
from pathlib import Path

from .workspace import WorkspaceManager


class FileTools:
    """
    Local file tools available to the coding agent.

    Current operations:

    - list_files
    - search_text
    - read_file
    - write_file
    - edit_file

    All paths are resolved by WorkspaceManager and therefore must stay
    inside the configured workspace.
    """

    MAX_WRITE_CHARS = 500_000
    MAX_READ_CHARS = 30_000
    MAX_READ_LINES = 500
    MAX_LIST_ENTRIES = 500

    MAX_SEARCH_RESULTS = 200
    MAX_SEARCH_FILE_BYTES = 1_000_000
    MAX_SEARCH_LINE_CHARS = 500

    SEARCH_IGNORED_DIRECTORIES = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
    }

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

        # Existing files must be inspected before targeted editing.
        # Paths are stored after WorkspaceManager has resolved them.
        self._read_files: set[Path] = set()

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
        A successful read also authorizes later targeted editing of the
        same file through edit_file().
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

            self._read_files.add(
                target
            )

            return self._json(
                {
                    "ok": True,
                    "path": self.workspace.relative_path(
                        target
                    ),
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
        Write a complete UTF-8 text file inside the workspace.

        Safety rule:

        - a file created during this FileTools instance may be rewritten;
        - a pre-existing file requires overwrite=True.

        Targeted changes to existing files should normally use
        edit_file() after read_file().
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
                    "path": self.workspace.relative_path(
                        target
                    ),
                    "bytes_written": len(
                        content.encode(
                            "utf-8"
                        )
                    ),
                    "overwrote_existing": existed_before,
                    "message": (
                        "File written successfully: "
                        f"{self.workspace.relative_path(target)}"
                    ),
                }
            )

        except Exception as exc:
            return self._json_error(
                exc
            )

    # ========================================================
    # edit_file
    # ========================================================

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
    ) -> str:
        """
        Replace one exact, unique text block inside an existing file.

        The target file must have been successfully inspected with
        read_file() by this FileTools instance. old_text must match
        exactly once; zero or multiple matches are rejected so the
        runtime never guesses which location the model intended.
        """

        try:
            if not isinstance(
                old_text,
                str,
            ):
                raise TypeError(
                    "old_text must be a string."
                )

            if not old_text:
                raise ValueError(
                    "old_text cannot be empty."
                )

            if not isinstance(
                new_text,
                str,
            ):
                raise TypeError(
                    "new_text must be a string."
                )

            if old_text == new_text:
                raise ValueError(
                    "new_text must differ from old_text."
                )

            target = self.workspace.resolve_file(
                path,
                must_exist=True,
            )

            if target not in self._read_files:
                return self._json(
                    {
                        "ok": False,
                        "path": self.workspace.relative_path(
                            target
                        ),
                        "error": (
                            "File must be read with read_file "
                            "before it can be edited: "
                            f"{self.workspace.relative_path(target)}"
                        ),
                    }
                )

            content = target.read_text(
                encoding="utf-8"
            )

            match_count = content.count(
                old_text
            )

            if match_count == 0:
                return self._json(
                    {
                        "ok": False,
                        "path": self.workspace.relative_path(
                            target
                        ),
                        "match_count": 0,
                        "error": (
                            "old_text was not found in the file. "
                            "Read the latest file contents and provide "
                            "an exact text block."
                        ),
                    }
                )

            if match_count > 1:
                return self._json(
                    {
                        "ok": False,
                        "path": self.workspace.relative_path(
                            target
                        ),
                        "match_count": match_count,
                        "error": (
                            "old_text matched multiple locations. "
                            "Provide more surrounding context so the "
                            "match is unique."
                        ),
                    }
                )

            updated = content.replace(
                old_text,
                new_text,
                1,
            )

            if len(updated) > self.MAX_WRITE_CHARS:
                raise ValueError(
                    "Edited file would be too large. "
                    f"Maximum size is "
                    f"{self.MAX_WRITE_CHARS} characters."
                )

            target.write_text(
                updated,
                encoding="utf-8",
            )

            return self._json(
                {
                    "ok": True,
                    "path": self.workspace.relative_path(
                        target
                    ),
                    "replacements": 1,
                    "bytes_written": len(
                        updated.encode(
                            "utf-8"
                        )
                    ),
                    "message": (
                        "File edited successfully: "
                        f"{self.workspace.relative_path(target)}"
                    ),
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
    # search_text
    # ========================================================

    def search_text(
        self,
        query: str,
        path: str = ".",
        file_pattern: str | None = None,
        max_results: int = 50,
    ) -> str:
        """
        Search UTF-8 text files for a literal substring.

        Search is bounded by workspace path checks, file size and result
        count. Common dependency/cache directories are skipped. Binary
        and non-UTF-8 files are ignored rather than returned as errors.
        """

        try:
            if not isinstance(
                query,
                str,
            ):
                raise TypeError(
                    "query must be a string."
                )

            if not query:
                raise ValueError(
                    "query cannot be empty."
                )

            if file_pattern is not None:
                if not isinstance(
                    file_pattern,
                    str,
                ):
                    raise TypeError(
                        "file_pattern must be a string or null."
                    )

                if not file_pattern.strip():
                    raise ValueError(
                        "file_pattern cannot be empty."
                    )

                file_pattern = file_pattern.strip()

            if (
                isinstance(
                    max_results,
                    bool,
                )
                or not isinstance(
                    max_results,
                    int,
                )
            ):
                raise TypeError(
                    "max_results must be an integer."
                )

            max_results = max(
                1,
                min(
                    max_results,
                    self.MAX_SEARCH_RESULTS,
                ),
            )

            search_root = self.workspace.resolve(
                path,
                must_exist=True,
            )

            if not (
                search_root.is_file()
                or search_root.is_dir()
            ):
                raise ValueError(
                    "Search path must be a file or directory."
                )

            matches: list[dict] = []
            searched_files = 0
            skipped_files = 0
            truncated = False

            for candidate in self._iter_search_files(
                search_root
            ):
                try:
                    resolved = candidate.resolve()

                    if not self.workspace.contains(
                        resolved
                    ):
                        skipped_files += 1
                        continue

                    if not resolved.is_file():
                        continue

                    relative = self.workspace.relative_path(
                        resolved
                    )

                    if (
                        file_pattern is not None
                        and not Path(relative).match(
                            file_pattern
                        )
                    ):
                        continue

                    if (
                        resolved.stat().st_size
                        > self.MAX_SEARCH_FILE_BYTES
                    ):
                        skipped_files += 1
                        continue

                    text = resolved.read_text(
                        encoding="utf-8"
                    )

                    if "\x00" in text:
                        skipped_files += 1
                        continue

                except (
                    OSError,
                    UnicodeDecodeError,
                    ValueError,
                ):
                    skipped_files += 1
                    continue

                searched_files += 1

                for line_number, line in enumerate(
                    text.splitlines(),
                    start=1,
                ):
                    if query not in line:
                        continue

                    display_line = line

                    if (
                        len(display_line)
                        > self.MAX_SEARCH_LINE_CHARS
                    ):
                        display_line = (
                            display_line[
                                : self.MAX_SEARCH_LINE_CHARS
                            ]
                            + "..."
                        )

                    matches.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "text": display_line,
                        }
                    )

                    if len(matches) >= max_results:
                        truncated = True
                        break

                if truncated:
                    break

            return self._json(
                {
                    "ok": True,
                    "query": query,
                    "path": self.workspace.relative_path(
                        search_root
                    ),
                    "file_pattern": file_pattern,
                    "matches": matches,
                    "count": len(matches),
                    "searched_files": searched_files,
                    "skipped_files": skipped_files,
                    "truncated": truncated,
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

    def _iter_search_files(
        self,
        search_root: Path,
    ):
        if search_root.is_file():
            yield search_root
            return

        for current_root, directory_names, file_names in os.walk(
            search_root,
            followlinks=False,
        ):
            directory_names[:] = [
                name
                for name in directory_names
                if name not in self.SEARCH_IGNORED_DIRECTORIES
            ]

            current_path = Path(
                current_root
            )

            for file_name in sorted(
                file_names
            ):
                yield current_path / file_name

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

from __future__ import annotations

from pathlib import Path


class WorkspaceManager:
    """
    Manage the filesystem boundary used by local agent tools.

    All file-oriented tools should resolve paths through this class
    instead of implementing their own path checks.

    This prevents ordinary path traversal such as:

        ../../secret.txt
        /etc/passwd

    Important:
    this is a path-safety boundary, not an operating-system sandbox.
    A program executed inside the workspace may still access resources
    allowed by the host operating system unless stronger isolation is
    added later.
    """

    def __init__(
        self,
        root: str | Path,
    ) -> None:
        self.root = Path(root).expanduser().resolve()

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ========================================================
    # Public path resolution
    # ========================================================

    def resolve(
        self,
        relative_path: str | Path,
        *,
        must_exist: bool = False,
    ) -> Path:
        """
        Resolve a workspace-relative path into an absolute safe path.

        Absolute paths and paths escaping the workspace are rejected.
        Existing symlinks are resolved by Path.resolve(), so a symlink
        that points outside the workspace is also rejected.
        """

        path = self._validate_relative_path(
            relative_path
        )

        target = (
            self.root
            / path
        ).resolve()

        if not self.contains(target):
            raise ValueError(
                "Path escapes the workspace."
            )

        if must_exist and not target.exists():
            raise FileNotFoundError(
                f"Path does not exist: {relative_path}"
            )

        return target

    def resolve_file(
        self,
        relative_path: str | Path,
        *,
        must_exist: bool = False,
    ) -> Path:
        """
        Resolve a path intended to represent a regular file.
        """

        target = self.resolve(
            relative_path,
            must_exist=must_exist,
        )

        if target == self.root:
            raise ValueError(
                "A file path cannot refer to the workspace root."
            )

        if target.exists() and target.is_dir():
            raise IsADirectoryError(
                f"Expected a file but found a directory: {relative_path}"
            )

        return target

    def resolve_directory(
        self,
        relative_path: str | Path = ".",
        *,
        must_exist: bool = True,
    ) -> Path:
        """
        Resolve a path intended to represent a directory.
        """

        target = self.resolve(
            relative_path,
            must_exist=must_exist,
        )

        if target.exists() and not target.is_dir():
            raise NotADirectoryError(
                f"Expected a directory: {relative_path}"
            )

        return target

    # ========================================================
    # Boundary helpers
    # ========================================================

    def contains(
        self,
        path: str | Path,
    ) -> bool:
        """
        Return True when a path is inside the workspace.
        """

        candidate = Path(path).resolve()

        try:
            candidate.relative_to(
                self.root
            )
            return True

        except ValueError:
            return False

    def relative_path(
        self,
        path: str | Path,
    ) -> str:
        """
        Convert a safe absolute path back to a workspace-relative path.
        """

        candidate = Path(path).resolve()

        if not self.contains(candidate):
            raise ValueError(
                "Path is outside the workspace."
            )

        relative = candidate.relative_to(
            self.root
        )

        if str(relative) == ".":
            return "."

        return relative.as_posix()

    # ========================================================
    # Validation
    # ========================================================

    @staticmethod
    def _validate_relative_path(
        relative_path: str | Path,
    ) -> Path:

        if not isinstance(
            relative_path,
            (str, Path),
        ):
            raise TypeError(
                "Path must be a string or pathlib.Path."
            )

        raw = str(relative_path)

        if "\x00" in raw:
            raise ValueError(
                "Path contains a null byte."
            )

        raw = raw.strip()

        if not raw:
            raise ValueError(
                "Path cannot be empty."
            )

        path = Path(raw)

        if path.is_absolute():
            raise ValueError(
                "Absolute paths are not allowed."
            )

        return path
from __future__ import annotations

import hashlib
import os

from pathlib import Path


class WorkspaceManager:
    """
    Manage the filesystem boundary used by local agent tools.

    All file-oriented tools should resolve paths through this class
    instead of implementing their own path checks.

    This prevents ordinary path traversal such as:

        ../../secret.txt
        /etc/passwd

    WorkspaceManager also provides a deterministic source-tree
    fingerprint. The agent uses that revision to bind successful
    validation evidence to the exact filesystem state that was checked.

    Important:
    this is a path-safety boundary, not an operating-system sandbox.
    A program executed inside the workspace may still access resources
    allowed by the host operating system unless stronger isolation is
    added later.
    """

    REVISION_IGNORED_DIRECTORIES = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
        "target",
        "htmlcov",
    }

    REVISION_IGNORED_FILES = {
        ".DS_Store",
        ".coverage",
    }

    HASH_CHUNK_SIZE = 1024 * 1024

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
    # Workspace revision
    # ========================================================

    def calculate_revision(
        self,
    ) -> str:
        """
        Return a deterministic SHA-256 fingerprint of workspace files.

        Paths and file bytes are hashed in sorted relative-path order.
        Common caches, dependency trees and generated build directories
        are deliberately excluded so validation itself does not dirty
        the revision merely by creating pytest caches or build outputs.

        Symlinks are hashed as link metadata rather than followed. This
        prevents revision calculation from reading outside the workspace.
        """

        digest = hashlib.sha256()

        for path in self._revision_entries():
            relative = path.relative_to(
                self.root
            ).as_posix()

            if path.is_symlink():
                digest.update(b"L\0")
                digest.update(
                    relative.encode("utf-8")
                )
                digest.update(b"\0")
                digest.update(
                    os.readlink(path).encode(
                        "utf-8",
                        errors="surrogateescape",
                    )
                )
                digest.update(b"\0")
                continue

            if not path.is_file():
                continue

            digest.update(b"F\0")
            digest.update(
                relative.encode("utf-8")
            )
            digest.update(b"\0")

            with path.open("rb") as file:
                while True:
                    chunk = file.read(
                        self.HASH_CHUNK_SIZE
                    )

                    if not chunk:
                        break

                    digest.update(chunk)

            digest.update(b"\0")

        return digest.hexdigest()

    def _revision_entries(
        self,
    ) -> list[Path]:
        entries: list[Path] = []

        for current_root, directories, files in os.walk(
            self.root,
            topdown=True,
            followlinks=False,
        ):
            directories[:] = sorted(
                directory
                for directory in directories
                if directory
                not in self.REVISION_IGNORED_DIRECTORIES
            )

            current = Path(current_root)

            for name in sorted(files):
                if name in self.REVISION_IGNORED_FILES:
                    continue

                entries.append(
                    current / name
                )

            # os.walk does not include symlinked directories in files.
            # Record them explicitly so changing a link target changes
            # the workspace revision without following the target.
            for name in sorted(directories):
                candidate = current / name

                if candidate.is_symlink():
                    entries.append(candidate)

        return sorted(
            entries,
            key=lambda path: (
                path.relative_to(self.root).as_posix()
            ),
        )

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

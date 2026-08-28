from pathlib import Path

import pytest

from tools.workspace import WorkspaceManager


def test_resolve_normal_relative_path(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")

    target = workspace.resolve("src/main.py")

    assert target == (workspace.root / "src/main.py").resolve()
    assert workspace.contains(target)


def test_rejects_parent_directory_escape(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")

    with pytest.raises(ValueError, match="escapes the workspace"):
        workspace.resolve("../secret.txt")


def test_rejects_absolute_path(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")

    with pytest.raises(ValueError, match="Absolute paths"):
        workspace.resolve("/etc/passwd")


def test_must_exist_rejects_missing_path(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")

    with pytest.raises(FileNotFoundError):
        workspace.resolve("missing.txt", must_exist=True)


def test_resolve_file_rejects_directory(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")
    (workspace.root / "src").mkdir()

    with pytest.raises(IsADirectoryError):
        workspace.resolve_file("src", must_exist=True)


def test_resolve_directory_rejects_file(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")
    (workspace.root / "main.py").write_text("print('ok')", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        workspace.resolve_directory("main.py")


def test_relative_path_round_trip(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")
    target = workspace.root / "a" / "b.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")

    assert workspace.relative_path(target) == "a/b.txt"


def test_symlink_escape_is_rejected(tmp_path: Path):
    workspace = WorkspaceManager(tmp_path / "workspace")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    link = workspace.root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="escapes the workspace"):
        workspace.resolve_file("link.txt", must_exist=True)

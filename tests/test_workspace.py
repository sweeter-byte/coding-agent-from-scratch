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


def test_workspace_revision_is_deterministic_and_changes_with_content(
    tmp_path: Path,
):
    workspace = WorkspaceManager(tmp_path / "workspace")

    source = workspace.root / "main.py"
    source.write_text("print('v1')\n", encoding="utf-8")

    first = workspace.calculate_revision()
    second = workspace.calculate_revision()

    assert first == second
    assert len(first) == 64

    source.write_text("print('v2')\n", encoding="utf-8")

    assert workspace.calculate_revision() != first


def test_workspace_revision_ignores_common_runtime_cache_directories(
    tmp_path: Path,
):
    workspace = WorkspaceManager(tmp_path / "workspace")

    (workspace.root / "main.py").write_text(
        "print('stable')\n",
        encoding="utf-8",
    )

    before = workspace.calculate_revision()

    cache = workspace.root / ".pytest_cache"
    cache.mkdir()
    (cache / "nodeids").write_text(
        "generated cache",
        encoding="utf-8",
    )

    pycache = workspace.root / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython.pyc").write_bytes(b"generated")

    assert workspace.calculate_revision() == before


def test_workspace_revision_tracks_symlink_without_following_external_target(
    tmp_path: Path,
):
    workspace = WorkspaceManager(tmp_path / "workspace")

    outside_one = tmp_path / "outside-one.txt"
    outside_two = tmp_path / "outside-two.txt"
    outside_one.write_text("secret-one", encoding="utf-8")
    outside_two.write_text("secret-two", encoding="utf-8")

    link = workspace.root / "linked.txt"
    link.symlink_to(outside_one)

    first = workspace.calculate_revision()

    link.unlink()
    link.symlink_to(outside_two)

    assert workspace.calculate_revision() != first

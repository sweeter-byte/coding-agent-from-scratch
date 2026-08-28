import json
from pathlib import Path

from tools.file_tools import FileTools


def decode(result: str) -> dict:
    return json.loads(result)


def test_write_then_read_file(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")

    write_result = decode(
        tools.write_file("src/main.py", "print('hello')\n")
    )
    read_result = decode(
        tools.read_file("src/main.py")
    )

    assert write_result["ok"] is True
    assert write_result["overwrote_existing"] is False
    assert read_result["ok"] is True
    assert read_result["content"] == "print('hello')\n"
    assert read_result["total_lines"] == 1


def test_created_file_can_be_rewritten_without_overwrite_flag(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")

    first = decode(tools.write_file("a.txt", "one"))
    second = decode(tools.write_file("a.txt", "two"))

    assert first["ok"] is True
    assert second["ok"] is True
    assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "two"


def test_preexisting_file_requires_overwrite_true(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "existing.txt").write_text("old", encoding="utf-8")

    tools = FileTools(root)

    refused = decode(tools.write_file("existing.txt", "new"))
    accepted = decode(
        tools.write_file("existing.txt", "new", overwrite=True)
    )

    assert refused["ok"] is False
    assert "overwrite=true" in refused["error"]
    assert accepted["ok"] is True
    assert (root / "existing.txt").read_text(encoding="utf-8") == "new"


def test_file_tools_reject_path_escape(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")

    result = decode(tools.write_file("../escape.txt", "bad"))

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]
    assert not (tmp_path / "escape.txt").exists()


def test_read_file_supports_line_range(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file("a.txt", "1\n2\n3\n4\n")

    result = decode(
        tools.read_file("a.txt", start_line=2, end_line=3)
    )

    assert result["ok"] is True
    assert result["content"] == "2\n3\n"
    assert result["start_line"] == 2
    assert result["end_line"] == 3


def test_read_file_rejects_invalid_line_range(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file("a.txt", "hello\n")

    result = decode(
        tools.read_file("a.txt", start_line=3, end_line=2)
    )

    assert result["ok"] is False
    assert "end_line" in result["error"]


def test_list_files_recursive(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file("a.txt", "a")
    tools.write_file("src/b.py", "b")

    result = decode(tools.list_files(recursive=True))
    paths = {entry["path"] for entry in result["entries"]}

    assert result["ok"] is True
    assert "a.txt" in paths
    assert "src" in paths
    assert "src/b.py" in paths


def test_list_files_respects_max_entries(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    for index in range(5):
        tools.write_file(f"{index}.txt", str(index))

    result = decode(tools.list_files(max_entries=2))

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["truncated"] is True

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


# ============================================================
# search_text
# ============================================================


def test_search_text_returns_path_line_and_text(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file(
        "src/app.py",
        "def greet():\n    return 'hello'\n\nprint(greet())\n",
    )

    result = decode(
        tools.search_text("greet", file_pattern="*.py")
    )

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["matches"][0] == {
        "path": "src/app.py",
        "line": 1,
        "text": "def greet():",
    }
    assert result["matches"][1]["line"] == 4


def test_search_text_respects_file_pattern(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file("a.py", "needle\n")
    tools.write_file("a.txt", "needle\n")

    result = decode(
        tools.search_text("needle", file_pattern="*.py")
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "a.py"


def test_search_text_can_search_one_file(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file("a.py", "target\n")
    tools.write_file("b.py", "target\n")

    result = decode(
        tools.search_text("target", path="b.py")
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "b.py"


def test_search_text_respects_max_results(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")
    tools.write_file(
        "many.txt",
        "\n".join(["needle"] * 10),
    )

    result = decode(
        tools.search_text("needle", max_results=3)
    )

    assert result["ok"] is True
    assert result["count"] == 3
    assert result["truncated"] is True


def test_search_text_rejects_path_escape(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")

    result = decode(
        tools.search_text("secret", path="../")
    )

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]


def test_search_text_skips_binary_and_non_utf8_files(tmp_path: Path):
    root = tmp_path / "workspace"
    tools = FileTools(root)

    (root / "binary.bin").write_bytes(b"needle\x00data")
    (root / "bad.bin").write_bytes(b"needle\xff")
    (root / "good.txt").write_text("needle\n", encoding="utf-8")

    result = decode(
        tools.search_text("needle")
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "good.txt"
    assert result["skipped_files"] >= 2


def test_search_text_skips_common_cache_directories(tmp_path: Path):
    root = tmp_path / "workspace"
    tools = FileTools(root)

    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("needle\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("needle\n", encoding="utf-8")

    result = decode(
        tools.search_text("needle")
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "src/main.py"


# ============================================================
# edit_file
# ============================================================


def test_edit_file_requires_read_before_edit(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    tools = FileTools(root)

    result = decode(
        tools.edit_file(
            "app.py",
            "value = 1",
            "value = 2",
        )
    )

    assert result["ok"] is False
    assert "must be read" in result["error"]
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"


def test_edit_file_replaces_one_unique_match_after_read(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "app.py"
    target.write_text(
        "def value():\n    return 1\n",
        encoding="utf-8",
    )
    tools = FileTools(root)

    read_result = decode(tools.read_file("app.py"))
    edit_result = decode(
        tools.edit_file(
            "app.py",
            "    return 1",
            "    return 2",
        )
    )

    assert read_result["ok"] is True
    assert edit_result["ok"] is True
    assert edit_result["replacements"] == 1
    assert target.read_text(encoding="utf-8") == "def value():\n    return 2\n"


def test_edit_file_rejects_missing_old_text(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    tools = FileTools(root)
    tools.read_file("app.py")

    result = decode(
        tools.edit_file(
            "app.py",
            "value = 999",
            "value = 2",
        )
    )

    assert result["ok"] is False
    assert result["match_count"] == 0
    assert "not found" in result["error"]


def test_edit_file_rejects_ambiguous_old_text(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text(
        "value = 1\nvalue = 1\n",
        encoding="utf-8",
    )
    tools = FileTools(root)
    tools.read_file("app.py")

    result = decode(
        tools.edit_file(
            "app.py",
            "value = 1",
            "value = 2",
        )
    )

    assert result["ok"] is False
    assert result["match_count"] == 2
    assert "multiple locations" in result["error"]


def test_edit_file_rejects_path_escape(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    tools = FileTools(root)

    result = decode(
        tools.edit_file(
            "../outside.py",
            "value = 1",
            "value = 2",
        )
    )

    assert result["ok"] is False
    assert "escapes the workspace" in result["error"]
    assert outside.read_text(encoding="utf-8") == "value = 1\n"


def test_edit_file_allows_deletion_with_empty_new_text(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "app.py"
    target.write_text("keep\nremove\n", encoding="utf-8")
    tools = FileTools(root)
    tools.read_file("app.py")

    result = decode(
        tools.edit_file(
            "app.py",
            "remove\n",
            "",
        )
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "keep\n"


# ============================================================
# sensitive-data policy
# ============================================================


def test_read_file_blocks_sensitive_path(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".env").write_text(
        "OPENAI_API_KEY=definitely-not-a-real-key\n",
        encoding="utf-8",
    )
    tools = FileTools(root)

    result = decode(tools.read_file(".env"))

    assert result["ok"] is False
    assert "Sensitive path" in result["error"]


def test_write_file_blocks_sensitive_path_but_allows_env_example(tmp_path: Path):
    tools = FileTools(tmp_path / "workspace")

    blocked = decode(
        tools.write_file(".env", "OPENAI_API_KEY=secret\n")
    )
    allowed = decode(
        tools.write_file(
            ".env.example",
            "OPENAI_API_KEY=your-key-here\n",
        )
    )

    assert blocked["ok"] is False
    assert "Sensitive path" in blocked["error"]
    assert allowed["ok"] is True


def test_list_files_hides_sensitive_entries(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".env").write_text("secret\n", encoding="utf-8")
    (root / ".env.example").write_text("placeholder\n", encoding="utf-8")
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_ed25519").write_text("secret\n", encoding="utf-8")
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    tools = FileTools(root)

    result = decode(tools.list_files())
    paths = {entry["path"] for entry in result["entries"]}

    assert ".env" not in paths
    assert ".ssh" not in paths
    assert ".ssh/id_ed25519" not in paths
    assert ".env.example" in paths
    assert "main.py" in paths


def test_search_text_skips_sensitive_files(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".env").write_text("needle=secret\n", encoding="utf-8")
    (root / "safe.txt").write_text("needle=safe\n", encoding="utf-8")
    tools = FileTools(root)

    result = decode(tools.search_text("needle"))

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "safe.txt"
    assert result["skipped_files"] >= 1

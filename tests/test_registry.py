import json
from pathlib import Path

from tools.registry import ToolRegistry


def decode(result: str) -> dict:
    return json.loads(result)


def test_registry_contains_expected_tools(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    assert set(registry.list_tools()) == {
        "list_files",
        "search_text",
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
    }


def test_get_schemas_returns_defensive_copy(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    first = registry.get_schemas()
    first[0]["function"]["name"] = "mutated"
    second = registry.get_schemas()

    names = {
        schema["function"]["name"]
        for schema in second
    }
    assert "mutated" not in names
    assert "read_file" in names
    assert "search_text" in names
    assert "edit_file" in names


def test_registry_dispatches_tool(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    result = decode(
        registry.execute(
            "write_file",
            {"path": "a.txt", "content": "hello"},
        )
    )

    assert result["ok"] is True
    assert (tmp_path / "workspace" / "a.txt").exists()


def test_registry_dispatches_search_and_edit_tools(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    registry = ToolRegistry(root)

    search_result = decode(
        registry.execute(
            "search_text",
            {"query": "value", "file_pattern": "*.py"},
        )
    )
    read_result = decode(
        registry.execute(
            "read_file",
            {"path": "app.py"},
        )
    )
    edit_result = decode(
        registry.execute(
            "edit_file",
            {
                "path": "app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            },
        )
    )

    assert search_result["ok"] is True
    assert search_result["count"] == 1
    assert read_result["ok"] is True
    assert edit_result["ok"] is True
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 2\n"


def test_unknown_tool_returns_structured_error(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    result = decode(registry.execute("does_not_exist", {}))

    assert result["ok"] is False
    assert result["tool"] == "does_not_exist"
    assert "Unknown tool" in result["error"]


def test_invalid_tool_arguments_return_structured_error(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    result = decode(
        registry.execute(
            "write_file",
            {"path": "a.txt"},
        )
    )

    assert result["ok"] is False
    assert result["tool"] == "write_file"
    assert "Invalid arguments" in result["error"]


def test_run_command_schema_exposes_controlled_cwd_and_pytest_guidance(
    tmp_path: Path,
):
    registry = ToolRegistry(tmp_path / "workspace")

    run_schema = next(
        schema
        for schema in registry.get_schemas()
        if schema["function"]["name"] == "run_command"
    )

    properties = run_schema["function"]["parameters"]["properties"]

    assert "cwd" in properties
    assert properties["cwd"]["default"] == "."
    assert properties["cwd"]["type"] == "string"
    assert "pytest" in run_schema["function"]["description"]

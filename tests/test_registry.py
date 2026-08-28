import json
from pathlib import Path

from tools.registry import ToolRegistry


def decode(result: str) -> dict:
    return json.loads(result)


def test_registry_contains_expected_tools(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")

    assert set(registry.list_tools()) == {
        "read_file",
        "write_file",
        "list_files",
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

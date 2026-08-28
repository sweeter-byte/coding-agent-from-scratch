# ============================================================
# Tool schemas exposed to the language model
# ============================================================


LIST_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": (
            "List files and directories inside the workspace. "
            "Use this to inspect the structure of an unfamiliar "
            "existing project."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative directory to list. "
                        "Defaults to '.'."
                    ),
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": (
                        "Whether to recursively list descendants."
                    ),
                    "default": True,
                },
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": (
                        "Maximum number of entries returned."
                    ),
                    "default": 200,
                },
            },
            "required": [],
        },
    },
}


SEARCH_TEXT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_text",
        "description": (
            "Search workspace text files for an exact literal "
            "substring and return matching file paths, line numbers, "
            "and lines. Use this to locate symbols, error strings, "
            "function names, or relevant code before reading files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Literal text to search for. Search is "
                        "case-sensitive."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative file or directory to "
                        "search. Defaults to '.'."
                    ),
                    "default": ".",
                },
                "file_pattern": {
                    "type": "string",
                    "description": (
                        "Optional glob pattern used to restrict files, "
                        "for example '*.py' or 'src/*.cpp'."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "description": (
                        "Maximum number of matching lines returned."
                    ),
                    "default": 50,
                },
            },
            "required": [
                "query",
            ],
        },
    },
}


READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file inside the workspace. "
            "Use this to inspect existing source code or a file "
            "created earlier in the task. A file must be read before "
            "it can be modified with edit_file. Large reads may be "
            "truncated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative file path, "
                        "for example 'src/main.cpp' "
                        "or 'solution.py'."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based first line to read. "
                        "Defaults to 1."
                    ),
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Optional 1-based final "
                        "line to read, inclusive."
                    ),
                },
            },
            "required": [
                "path",
            ],
        },
    },
}


WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Write a complete UTF-8 text file inside the workspace. "
            "Prefer this for creating new files or intentionally "
            "rewriting a complete file. Files created during the "
            "current run may be rewritten. A file that already "
            "existed before the current run requires overwrite=true. "
            "For small targeted changes to an existing file, prefer "
            "read_file followed by edit_file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative file path, "
                        "for example 'main.cpp' "
                        "or 'src/solution.py'."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Complete file content to write."
                    ),
                },
                "overwrite": {
                    "type": "boolean",
                    "description": (
                        "Whether an already-existing workspace "
                        "file may be overwritten. Use true only "
                        "when a complete rewrite is intentionally "
                        "required by the task."
                    ),
                    "default": False,
                },
            },
            "required": [
                "path",
                "content",
            ],
        },
    },
}


EDIT_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": (
            "Make one targeted edit to an existing UTF-8 text file. "
            "The file must first be inspected with read_file. "
            "old_text must match exactly once; if it is missing or "
            "ambiguous, the edit is rejected and you should read the "
            "latest contents and provide more surrounding context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative existing file path."
                    ),
                },
                "old_text": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Exact existing text block to replace. Include "
                        "enough surrounding context for a unique match."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "description": (
                        "Replacement text block. It may be empty to "
                        "delete the matched old_text."
                    ),
                },
            },
            "required": [
                "path",
                "old_text",
                "new_text",
            ],
        },
    },
}


RUN_COMMAND_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run an allowed compiler, interpreter, generated "
            "executable, or test command locally inside the "
            "workspace. Provide argv as an array; shell "
            "command strings and shell operators are not supported."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "minItems": 1,
                    "description": (
                        "Command argument vector. Example: "
                        '[\"g++\", \"main.cpp\", \"-o\", \"main\"]'
                    ),
                },
                "purpose": {
                    "type": "string",
                    "enum": [
                        "compile",
                        "run",
                        "test",
                    ],
                    "description": (
                        "Why this command is being executed."
                    ),
                },
                "stdin": {
                    "type": "string",
                    "description": (
                        "Optional standard input supplied "
                        "to the process."
                    ),
                    "default": "",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": (
                        "Maximum local execution time "
                        "in seconds."
                    ),
                    "default": 20,
                },
            },
            "required": [
                "argv",
                "purpose",
            ],
        },
    },
}


# CodingAgent should obtain schemas through:
#
#     ToolRegistry.get_schemas()
#
# rather than importing TOOLS directly.

TOOLS = [
    LIST_FILES_SCHEMA,
    SEARCH_TEXT_SCHEMA,
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    EDIT_FILE_SCHEMA,
    RUN_COMMAND_SCHEMA,
]

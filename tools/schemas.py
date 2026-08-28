# ============================================================
# Tool schemas exposed to the language model
# ============================================================


READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file inside the workspace. "
            "Use this to inspect existing source code or a file "
            "created earlier in the task. "
            "Large reads may be truncated."
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
            "Write a complete UTF-8 text file inside the "
            "workspace. Files created during the current run "
            "may be rewritten when fixing code. "
            "A file that already existed before the current "
            "run requires overwrite=true."
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
                        "file may be overwritten. "
                        "Use true only when modifying that file "
                        "is intentionally required by the task."
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


LIST_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": (
            "List files and directories inside the workspace. "
            "Use this before reading an unfamiliar "
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
                        "Whether to recursively "
                        "list descendants."
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
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    LIST_FILES_SCHEMA,
    RUN_COMMAND_SCHEMA,
]
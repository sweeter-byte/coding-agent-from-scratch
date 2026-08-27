# ============================================================
# Tool schemas exposed to the LLM
# ============================================================


WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Create a new source code file inside the workspace. "
            "You may rewrite a file that you created earlier in this task "
            "when fixing compilation or runtime errors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path of the file to create, "
                        "for example 'quick_sort.cpp' or 'solution.py'."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "The complete source code that should be "
                        "written to the file."
                    ),
                },
            },
            "required": [
                "path",
                "content",
            ],
        },
    },
}


RUN_COMMAND_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run a compiler, interpreter, generated executable, "
            "or test command inside the workspace. "
            "The command must be represented as an argv array "
            "rather than a shell command string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": (
                        "Command arguments. "
                        "For example: "
                        '["g++", "main.cpp", "-o", "main"]'
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
                        "The purpose of executing this command."
                    ),
                },
                "stdin": {
                    "type": "string",
                    "description": (
                        "Optional standard input supplied to the program."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Maximum execution time in seconds."
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


TOOLS = [
    WRITE_FILE_SCHEMA,
    RUN_COMMAND_SCHEMA,
]
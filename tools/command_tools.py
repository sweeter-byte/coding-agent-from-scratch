from __future__ import annotations

import json
import os
import subprocess

from pathlib import Path

from .workspace import WorkspaceManager


class CommandTools:
    """
    Execute selected local commands inside the workspace.

    Safety decisions in this first version:

    - shell=False is always used;
    - argv must be a list, never a shell command string;
    - only selected compiler/interpreter commands are allowed;
    - generated executables must live inside the workspace;
    - model/API credentials are removed from the child environment;
    - execution time and captured output are bounded.

    Important:
    this is NOT a real OS sandbox. Code executed by the host process may
    still access resources allowed by the current operating-system user.
    """

    PYTHON_EXECUTABLES = {
        "python",
        "python3",
        "py",
    }

    COMPILERS = {
        "g++",
        "clang++",
    }

    ALLOWED_PURPOSES = {
        "compile",
        "run",
        "test",
    }

    MAX_TIMEOUT_SECONDS = 30
    MAX_OUTPUT_CHARS = 12_000
    MAX_STDIN_CHARS = 100_000
    MAX_ARGV_ITEMS = 128
    MAX_ARGUMENT_CHARS = 20_000

    DISALLOWED_PYTHON_MODES = {
        "-c",
        "-m",
        "-",
    }

    def __init__(
        self,
        workspace: (
            str
            | Path
            | WorkspaceManager
        ),
    ) -> None:

        if isinstance(
            workspace,
            WorkspaceManager,
        ):
            self.workspace = workspace

        else:
            self.workspace = (
                WorkspaceManager(
                    workspace
                )
            )

    # ========================================================
    # run_command
    # ========================================================

    def run_command(
        self,
        argv: list[str],
        purpose: str,
        stdin: str = "",
        timeout_seconds: int = 20,
    ) -> str:
        """
        Execute one command inside the workspace.

        Example:

            ["g++", "main.cpp", "-o", "main"]

        followed by:

            ["./main"]

        shell=False is always used.
        """

        try:
            self._validate_request(
                argv=argv,
                purpose=purpose,
                stdin=stdin,
                timeout_seconds=(
                    timeout_seconds
                ),
            )

            command = (
                self._prepare_command(
                    argv
                )
            )

            timeout_seconds = max(
                1,
                min(
                    timeout_seconds,
                    self.MAX_TIMEOUT_SECONDS,
                ),
            )

            result = subprocess.run(
                command,
                cwd=self.workspace.root,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
                env=(
                    self
                    ._sanitized_environment()
                ),
            )

            (
                stdout,
                stdout_truncated,
            ) = self._truncate_output(
                result.stdout or ""
            )

            (
                stderr,
                stderr_truncated,
            ) = self._truncate_output(
                result.stderr or ""
            )

            return self._json(
                {
                    "ok": (
                        result.returncode
                        == 0
                    ),
                    "purpose": purpose,
                    "argv": argv,
                    "returncode": (
                        result.returncode
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": (
                        stdout_truncated
                    ),
                    "stderr_truncated": (
                        stderr_truncated
                    ),
                }
            )

        except subprocess.TimeoutExpired as exc:

            stdout = (
                self
                ._normalize_timeout_output(
                    exc.stdout
                )
            )

            stderr = (
                self
                ._normalize_timeout_output(
                    exc.stderr
                )
            )

            (
                stdout,
                stdout_truncated,
            ) = self._truncate_output(
                stdout
            )

            (
                stderr,
                stderr_truncated,
            ) = self._truncate_output(
                stderr
            )

            return self._json(
                {
                    "ok": False,
                    "purpose": purpose,
                    "argv": argv,
                    "error": (
                        "Command timed out after "
                        f"{timeout_seconds} "
                        "second(s)."
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": (
                        stdout_truncated
                    ),
                    "stderr_truncated": (
                        stderr_truncated
                    ),
                }
            )

        except Exception as exc:
            return self._json(
                {
                    "ok": False,
                    "purpose": purpose,
                    "argv": argv,
                    "error": str(exc),
                }
            )

    # ========================================================
    # Request validation
    # ========================================================

    def _validate_request(
        self,
        argv: list[str],
        purpose: str,
        stdin: str,
        timeout_seconds: int,
    ) -> None:

        if not isinstance(
            argv,
            list,
        ):
            raise TypeError(
                "argv must be a list of strings."
            )

        if not argv:
            raise ValueError(
                "argv cannot be empty."
            )

        if len(argv) > self.MAX_ARGV_ITEMS:
            raise ValueError(
                "argv contains too many arguments."
            )

        total_chars = 0

        for argument in argv:

            if not isinstance(
                argument,
                str,
            ):
                raise TypeError(
                    "Every argv element must "
                    "be a string."
                )

            if "\x00" in argument:
                raise ValueError(
                    "Command arguments cannot "
                    "contain null bytes."
                )

            total_chars += len(
                argument
            )

        if (
            total_chars
            > self.MAX_ARGUMENT_CHARS
        ):
            raise ValueError(
                "Command arguments are too large."
            )

        if (
            purpose
            not in self.ALLOWED_PURPOSES
        ):
            raise ValueError(
                "purpose must be one of: "
                + ", ".join(
                    sorted(
                        self.ALLOWED_PURPOSES
                    )
                )
            )

        if not isinstance(
            stdin,
            str,
        ):
            raise TypeError(
                "stdin must be a string."
            )

        if (
            len(stdin)
            > self.MAX_STDIN_CHARS
        ):
            raise ValueError(
                "stdin is too large."
            )

        if (
            isinstance(
                timeout_seconds,
                bool,
            )
            or not isinstance(
                timeout_seconds,
                int,
            )
        ):
            raise TypeError(
                "timeout_seconds must "
                "be an integer."
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must "
                "be greater than 0."
            )

    # ========================================================
    # Command preparation
    # ========================================================

    def _prepare_command(
        self,
        argv: list[str],
    ) -> list[str]:

        executable = argv[0]

        if (
            executable
            in self.PYTHON_EXECUTABLES
        ):
            return (
                self
                ._prepare_python_command(
                    argv
                )
            )

        if (
            executable
            in self.COMPILERS
        ):
            return (
                self
                ._prepare_compiler_command(
                    argv
                )
            )

        # Otherwise assume it is an executable
        # generated inside workspace.
        return (
            self
            ._prepare_workspace_executable(
                argv
            )
        )

    def _prepare_python_command(
        self,
        argv: list[str],
    ) -> list[str]:

        if len(argv) < 2:
            raise ValueError(
                "Python validation must specify "
                "a workspace script."
            )

        for argument in argv[1:]:

            if (
                argument
                in self.DISALLOWED_PYTHON_MODES
            ):
                raise ValueError(
                    "Inline/module Python execution "
                    "is not allowed. Run a Python "
                    "source file inside the workspace."
                )

        allowed_flags = {
            "-B",
            "-u",
            "-O",
            "-OO",
        }

        script_index: int | None = None

        for index, argument in enumerate(
            argv[1:],
            start=1,
        ):
            if argument in allowed_flags:
                continue

            if argument.startswith("-"):
                raise ValueError(
                    "Unsupported Python option: "
                    f"{argument}"
                )

            script_index = index
            break

        if script_index is None:
            raise ValueError(
                "Python validation must "
                "specify a source file."
            )

        script = (
            self.workspace
            .resolve_file(
                argv[script_index],
                must_exist=True,
            )
        )

        prepared = argv.copy()

        prepared[
            script_index
        ] = str(script)

        return prepared

    def _prepare_compiler_command(
        self,
        argv: list[str],
    ) -> list[str]:

        if len(argv) < 2:
            raise ValueError(
                "Compiler command is "
                "missing arguments."
            )

        prepared = argv.copy()

        index = 1

        while index < len(
            prepared
        ):
            argument = prepared[
                index
            ]

            # Example:
            #
            # g++ main.cpp -o main

            if argument == "-o":

                if (
                    index + 1
                    >= len(prepared)
                ):
                    raise ValueError(
                        "Compiler option '-o' "
                        "requires an output path."
                    )

                output_path = (
                    self.workspace
                    .resolve_file(
                        prepared[
                            index + 1
                        ]
                    )
                )

                prepared[
                    index + 1
                ] = str(
                    output_path
                )

                index += 2
                continue

            if self._looks_like_compiler_file(
                argument
            ):
                file_path = (
                    self.workspace
                    .resolve_file(
                        argument,
                        must_exist=True,
                    )
                )

                prepared[
                    index
                ] = str(
                    file_path
                )

            elif Path(
                argument
            ).is_absolute():
                raise ValueError(
                    "Absolute path arguments "
                    "are not allowed in "
                    "compiler commands."
                )

            index += 1

        return prepared

    def _prepare_workspace_executable(
        self,
        argv: list[str],
    ) -> list[str]:

        candidate = (
            self.workspace
            .resolve_file(
                argv[0],
                must_exist=True,
            )
        )

        prepared = argv.copy()

        prepared[0] = str(
            candidate
        )

        return prepared

    # ========================================================
    # Compiler helpers
    # ========================================================

    @staticmethod
    def _looks_like_compiler_file(
        argument: str,
    ) -> bool:

        if argument.startswith("-"):
            return False

        suffix = (
            Path(argument)
            .suffix
            .lower()
        )

        return suffix in {
            ".c",
            ".cc",
            ".cpp",
            ".cxx",
            ".h",
            ".hh",
            ".hpp",
            ".o",
            ".obj",
        }

    # ========================================================
    # Child process environment
    # ========================================================

    @staticmethod
    def _sanitized_environment(
    ) -> dict[str, str]:
        """
        Prevent generated programs from directly inheriting
        common API credentials from the agent process.
        """

        environment = dict(
            os.environ
        )

        explicit_sensitive = {
            "QWEN_API_KEY",
            "DASHSCOPE_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }

        for key in list(
            environment
        ):
            upper = key.upper()

            if (
                upper
                in explicit_sensitive

                or upper.endswith(
                    "_API_KEY"
                )

                or upper.endswith(
                    "_ACCESS_TOKEN"
                )

                or upper.endswith(
                    "_REFRESH_TOKEN"
                )

                or upper.endswith(
                    "_SECRET"
                )

                or upper.endswith(
                    "_PASSWORD"
                )
            ):
                environment.pop(
                    key,
                    None,
                )

        return environment

    # ========================================================
    # Output helpers
    # ========================================================

    @classmethod
    def _truncate_output(
        cls,
        output: str,
    ) -> tuple[str, bool]:

        if (
            len(output)
            <= cls.MAX_OUTPUT_CHARS
        ):
            return output, False

        return (
            output[
                : cls.MAX_OUTPUT_CHARS
            ]
            + "\n...[output truncated]",
            True,
        )

    @staticmethod
    def _normalize_timeout_output(
        output: str | bytes | None,
    ) -> str:

        if output is None:
            return ""

        if isinstance(
            output,
            bytes,
        ):
            return output.decode(
                "utf-8",
                errors="replace",
            )

        return output

    @staticmethod
    def _json(
        payload: dict,
    ) -> str:

        return json.dumps(
            payload,
            ensure_ascii=False,
        )
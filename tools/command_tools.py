from __future__ import annotations

import json
import os
import subprocess

from pathlib import Path

from security import SensitiveDataPolicy

from .workspace import WorkspaceManager


class CommandTools:
    """
    Execute selected local commands inside the workspace.

    Safety decisions:

    - shell=False is always used;
    - argv must be a list, never a shell command string;
    - the working directory must remain inside the workspace;
    - only selected compilers, interpreters, build/test commands,
      or executables generated inside the workspace are allowed;
    - inline Python code and arbitrary Python modules are rejected;
    - common shell executables are explicitly rejected;
    - model/API credentials are removed from the child environment;
    - execution time, stdin size, argv size, and captured output are bounded.

    Important:
    this is NOT a real OS sandbox. Code executed by the host process may
    still access resources allowed by the current operating-system user.
    """

    PYTHON_EXECUTABLES = {
        "python",
        "python3",
        "py",
    }

    PYTEST_EXECUTABLES = {
        "pytest",
        "pytest-3",
    }

    COMPILERS = {
        "g++",
        "clang++",
    }

    CMAKE_EXECUTABLES = {
        "cmake",
    }

    CTEST_EXECUTABLES = {
        "ctest",
    }

    DISALLOWED_SHELL_EXECUTABLES = {
        "sh",
        "bash",
        "dash",
        "zsh",
        "fish",
        "powershell",
        "pwsh",
        "cmd",
        "cmd.exe",
    }

    SHELL_OPERATOR_TOKENS = {
        "&&",
        "||",
        ";",
        "|",
        ">",
        ">>",
        "<",
        "<<",
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

    PYTHON_FLAGS = {
        "-B",
        "-u",
        "-O",
        "-OO",
    }

    PYTEST_FLAG_OPTIONS = {
        "-q",
        "-v",
        "-vv",
        "-s",
        "-x",
        "--exitfirst",
        "--disable-warnings",
        "--strict-markers",
        "--strict-config",
        "--collect-only",
        "--output-on-failure",
    }

    PYTEST_VALUE_OPTIONS = {
        "-k",
        "-m",
        "--maxfail",
        "--tb",
        "--color",
    }

    PYTEST_PREFIX_OPTIONS = {
        "--maxfail=",
        "--tb=",
        "--color=",
    }

    CTEST_FLAG_OPTIONS = {
        "-V",
        "--verbose",
        "-N",
        "--show-only",
        "--output-on-failure",
        "--stop-on-failure",
    }

    CTEST_VALUE_OPTIONS = {
        "-R",
        "-E",
        "-j",
        "--parallel",
        "--no-tests",
    }

    CTEST_PREFIX_OPTIONS = {
        "--no-tests=",
    }

    CMAKE_BUILD_VALUE_OPTIONS = {
        "--target",
        "--config",
        "--parallel",
    }

    CMAKE_CONFIGURE_PREFIX_OPTIONS = {
        "-DCMAKE_BUILD_TYPE=",
    }

    COMPILER_PATH_OPTIONS = {
        "-I",
        "-L",
        "-include",
        "-isystem",
        "-iquote",
    }

    COMPILER_JOINED_PATH_PREFIXES = {
        "-I",
        "-L",
    }

    def __init__(
        self,
        workspace: str | Path | WorkspaceManager,
    ) -> None:
        if isinstance(workspace, WorkspaceManager):
            self.workspace = workspace
        else:
            self.workspace = WorkspaceManager(workspace)

    # ========================================================
    # run_command
    # ========================================================

    def run_command(
        self,
        argv: list[str],
        purpose: str,
        stdin: str = "",
        timeout_seconds: int = 20,
        cwd: str = ".",
    ) -> str:
        """
        Execute one controlled command inside the workspace.

        Examples:

            ["python", "script.py"]
            ["python", "-m", "pytest", "-q"]
            ["pytest", "tests/test_example.py", "-q"]
            ["g++", "main.cpp", "-o", "main"]
            ["cmake", "-S", ".", "-B", "build"]
            ["cmake", "--build", "build"]
            ["ctest", "--test-dir", "build", "--output-on-failure"]

        shell=False is always used.
        """

        normalized_cwd = cwd
        runtime_purpose = purpose
        validation_eligible = False
        validation_reason = "command_not_executed"

        try:
            self._validate_request(
                argv=argv,
                purpose=purpose,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
                cwd=cwd,
            )

            cwd_path = self.workspace.resolve_directory(
                cwd,
                must_exist=True,
            )
            normalized_cwd = self.workspace.relative_path(cwd_path)

            command = self._prepare_command(
                argv=argv,
                cwd_path=cwd_path,
            )

            runtime_purpose = self._infer_command_purpose(argv)
            (
                validation_eligible,
                validation_reason,
            ) = self._validation_eligibility(
                argv=argv,
                purpose=runtime_purpose,
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
                cwd=cwd_path,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
                env=self._sanitized_environment(),
            )

            stdout, stdout_truncated = self._truncate_output(
                result.stdout or ""
            )
            stderr, stderr_truncated = self._truncate_output(
                result.stderr or ""
            )

            return self._json(
                {
                    "ok": result.returncode == 0,
                    "purpose": runtime_purpose,
                    "validation_eligible": validation_eligible,
                    "validation_reason": validation_reason,
                    "argv": argv,
                    "cwd": normalized_cwd,
                    "returncode": result.returncode,
                    "timed_out": False,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                }
            )

        except subprocess.TimeoutExpired as exc:
            stdout = self._normalize_timeout_output(exc.stdout)
            stderr = self._normalize_timeout_output(exc.stderr)

            stdout, stdout_truncated = self._truncate_output(stdout)
            stderr, stderr_truncated = self._truncate_output(stderr)

            return self._json(
                {
                    "ok": False,
                    "purpose": runtime_purpose,
                    "validation_eligible": validation_eligible,
                    "validation_reason": validation_reason,
                    "argv": argv,
                    "cwd": normalized_cwd,
                    "returncode": None,
                    "timed_out": True,
                    "error": (
                        "Command timed out after "
                        f"{timeout_seconds} second(s)."
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                }
            )

        except Exception as exc:
            return self._json(
                {
                    "ok": False,
                    "purpose": runtime_purpose,
                    "validation_eligible": validation_eligible,
                    "validation_reason": validation_reason,
                    "argv": argv,
                    "cwd": normalized_cwd,
                    "returncode": None,
                    "timed_out": False,
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
        cwd: str,
    ) -> None:
        if not isinstance(argv, list):
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
            if not isinstance(argument, str):
                raise TypeError(
                    "Every argv element must be a string."
                )

            if "\x00" in argument:
                raise ValueError(
                    "Command arguments cannot contain null bytes."
                )

            if argument in self.SHELL_OPERATOR_TOKENS:
                raise ValueError(
                    "Shell operators are not supported."
                )

            total_chars += len(argument)

        if total_chars > self.MAX_ARGUMENT_CHARS:
            raise ValueError(
                "Command arguments are too large."
            )

        if purpose not in self.ALLOWED_PURPOSES:
            raise ValueError(
                "purpose must be one of: "
                + ", ".join(sorted(self.ALLOWED_PURPOSES))
            )

        expected_purpose = self._infer_command_purpose(argv)

        if purpose != expected_purpose:
            raise ValueError(
                "purpose does not match the command type: "
                f"expected '{expected_purpose}' for {argv[0]!r}."
            )

        if not isinstance(stdin, str):
            raise TypeError(
                "stdin must be a string."
            )

        if len(stdin) > self.MAX_STDIN_CHARS:
            raise ValueError(
                "stdin is too large."
            )

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
        ):
            raise TypeError(
                "timeout_seconds must be an integer."
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than 0."
            )

        if not isinstance(cwd, str):
            raise TypeError(
                "cwd must be a workspace-relative string."
            )

        if not cwd.strip():
            raise ValueError(
                "cwd cannot be empty."
            )

    # ========================================================
    # Runtime-owned command semantics
    # ========================================================

    def _infer_command_purpose(
        self,
        argv: list[str],
    ) -> str:
        """Infer compile/run/test from argv instead of trusting the model."""

        executable = argv[0]

        if (
            executable in self.COMPILERS
            or executable in self.CMAKE_EXECUTABLES
        ):
            return "compile"

        if (
            executable in self.PYTEST_EXECUTABLES
            or executable in self.CTEST_EXECUTABLES
        ):
            return "test"

        if executable in self.PYTHON_EXECUTABLES:
            index = 1
            while index < len(argv) and argv[index] in self.PYTHON_FLAGS:
                index += 1

            if (
                index + 1 < len(argv)
                and argv[index] == "-m"
                and argv[index + 1] == "pytest"
            ):
                return "test"

            return "run"

        return "run"

    def _validation_eligibility(
        self,
        argv: list[str],
        purpose: str,
    ) -> tuple[bool, str]:
        """
        Return whether a successful command may create validation evidence.
        """

        if purpose == "compile":
            return False, "compile_only"

        if purpose == "test" and self._is_pytest_command(argv):
            if "--collect-only" in argv:
                return False, "pytest_collect_only"

        if purpose == "test" and argv[0] in self.CTEST_EXECUTABLES:
            if "-N" in argv or "--show-only" in argv:
                return False, "ctest_list_only"

        return True, "eligible"

    def _is_pytest_command(
        self,
        argv: list[str],
    ) -> bool:
        if argv[0] in self.PYTEST_EXECUTABLES:
            return True

        if argv[0] not in self.PYTHON_EXECUTABLES:
            return False

        index = 1
        while index < len(argv) and argv[index] in self.PYTHON_FLAGS:
            index += 1

        return (
            index + 1 < len(argv)
            and argv[index] == "-m"
            and argv[index + 1] == "pytest"
        )

    # ========================================================
    # Command preparation
    # ========================================================

    def _prepare_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        executable = argv[0]

        if executable in self.DISALLOWED_SHELL_EXECUTABLES:
            raise ValueError(
                f"Shell executable is not allowed: {executable}"
            )

        if executable in self.PYTHON_EXECUTABLES:
            return self._prepare_python_command(
                argv=argv,
                cwd_path=cwd_path,
            )

        if executable in self.PYTEST_EXECUTABLES:
            return self._prepare_pytest_command(
                argv=argv,
                cwd_path=cwd_path,
                start_index=1,
            )

        if executable in self.COMPILERS:
            return self._prepare_compiler_command(
                argv=argv,
                cwd_path=cwd_path,
            )

        if executable in self.CMAKE_EXECUTABLES:
            return self._prepare_cmake_command(
                argv=argv,
                cwd_path=cwd_path,
            )

        if executable in self.CTEST_EXECUTABLES:
            return self._prepare_ctest_command(
                argv=argv,
                cwd_path=cwd_path,
            )

        return self._prepare_workspace_executable(
            argv=argv,
            cwd_path=cwd_path,
        )

    # ========================================================
    # Python / pytest
    # ========================================================

    def _prepare_python_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        if len(argv) < 2:
            raise ValueError(
                "Python execution must specify a workspace script "
                "or the allowed pytest module."
            )

        prepared = argv.copy()
        index = 1

        while index < len(prepared) and prepared[index] in self.PYTHON_FLAGS:
            index += 1

        if index >= len(prepared):
            raise ValueError(
                "Python execution must specify a source file or pytest."
            )

        mode_or_script = prepared[index]

        if mode_or_script == "-c" or mode_or_script == "-":
            raise ValueError(
                "Inline Python execution is not allowed."
            )

        if mode_or_script == "-m":
            if index + 1 >= len(prepared):
                raise ValueError(
                    "Python '-m' requires a module name."
                )

            module = prepared[index + 1]

            if module != "pytest":
                raise ValueError(
                    "Only 'python -m pytest' is allowed for module execution."
                )

            return self._prepare_pytest_command(
                argv=prepared,
                cwd_path=cwd_path,
                start_index=index + 2,
            )

        if mode_or_script.startswith("-"):
            raise ValueError(
                f"Unsupported Python option: {mode_or_script}"
            )

        script = self._resolve_file_from_cwd(
            cwd_path,
            mode_or_script,
            must_exist=True,
        )

        prepared[index] = str(script)
        return prepared

    def _prepare_pytest_command(
        self,
        argv: list[str],
        cwd_path: Path,
        start_index: int,
    ) -> list[str]:
        prepared = argv.copy()
        index = start_index

        while index < len(prepared):
            argument = prepared[index]

            if argument in self.PYTEST_FLAG_OPTIONS:
                index += 1
                continue

            if argument in self.PYTEST_VALUE_OPTIONS:
                if index + 1 >= len(prepared):
                    raise ValueError(
                        f"Pytest option '{argument}' requires a value."
                    )
                index += 2
                continue

            if any(
                argument.startswith(prefix)
                for prefix in self.PYTEST_PREFIX_OPTIONS
            ):
                index += 1
                continue

            if argument.startswith("-"):
                raise ValueError(
                    f"Unsupported pytest option: {argument}"
                )

            prepared[index] = self._resolve_pytest_target(
                cwd_path,
                argument,
            )
            index += 1

        return prepared

    def _resolve_pytest_target(
        self,
        cwd_path: Path,
        target: str,
    ) -> str:
        path_part, separator, node_part = target.partition("::")

        if not path_part:
            raise ValueError(
                "Pytest target path cannot be empty."
            )

        resolved = self._resolve_path_from_cwd(
            cwd_path,
            path_part,
            must_exist=True,
        )

        normalized = str(resolved)

        if separator:
            normalized += "::" + node_part

        return normalized

    # ========================================================
    # C/C++ compiler
    # ========================================================

    def _prepare_compiler_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        if len(argv) < 2:
            raise ValueError(
                "Compiler command is missing arguments."
            )

        prepared = argv.copy()
        index = 1

        while index < len(prepared):
            argument = prepared[index]

            if argument == "-o":
                if index + 1 >= len(prepared):
                    raise ValueError(
                        "Compiler option '-o' requires an output path."
                    )

                output_path = self._resolve_file_from_cwd(
                    cwd_path,
                    prepared[index + 1],
                    must_exist=False,
                )
                prepared[index + 1] = str(output_path)
                index += 2
                continue

            if argument in self.COMPILER_PATH_OPTIONS:
                if index + 1 >= len(prepared):
                    raise ValueError(
                        f"Compiler option '{argument}' requires a path."
                    )

                path = self._resolve_path_from_cwd(
                    cwd_path,
                    prepared[index + 1],
                    must_exist=True,
                )
                prepared[index + 1] = str(path)
                index += 2
                continue

            joined_prefix = next(
                (
                    prefix
                    for prefix in self.COMPILER_JOINED_PATH_PREFIXES
                    if argument.startswith(prefix)
                    and argument != prefix
                ),
                None,
            )

            if joined_prefix is not None:
                raw_path = argument[len(joined_prefix):]
                path = self._resolve_path_from_cwd(
                    cwd_path,
                    raw_path,
                    must_exist=True,
                )
                prepared[index] = joined_prefix + str(path)
                index += 1
                continue

            if self._looks_like_compiler_file(argument):
                file_path = self._resolve_file_from_cwd(
                    cwd_path,
                    argument,
                    must_exist=True,
                )
                prepared[index] = str(file_path)

            elif Path(argument).is_absolute():
                raise ValueError(
                    "Absolute path arguments are not allowed in compiler commands."
                )

            index += 1

        return prepared

    # ========================================================
    # CMake / CTest
    # ========================================================

    def _prepare_cmake_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        if len(argv) < 2:
            raise ValueError(
                "cmake requires configure or build arguments."
            )

        if argv[1] == "--build":
            return self._prepare_cmake_build_command(
                argv=argv,
                cwd_path=cwd_path,
            )

        return self._prepare_cmake_configure_command(
            argv=argv,
            cwd_path=cwd_path,
        )

    def _prepare_cmake_configure_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        prepared = argv.copy()
        source_seen = False
        build_seen = False
        index = 1

        while index < len(prepared):
            argument = prepared[index]

            if argument == "-S":
                if index + 1 >= len(prepared):
                    raise ValueError("cmake -S requires a source directory.")
                source = self._resolve_directory_from_cwd(
                    cwd_path,
                    prepared[index + 1],
                    must_exist=True,
                )
                prepared[index + 1] = str(source)
                source_seen = True
                index += 2
                continue

            if argument == "-B":
                if index + 1 >= len(prepared):
                    raise ValueError("cmake -B requires a build directory.")
                build = self._resolve_path_from_cwd(
                    cwd_path,
                    prepared[index + 1],
                    must_exist=False,
                )
                prepared[index + 1] = str(build)
                build_seen = True
                index += 2
                continue

            if argument == "--fresh":
                index += 1
                continue

            if any(
                argument.startswith(prefix)
                for prefix in self.CMAKE_CONFIGURE_PREFIX_OPTIONS
            ):
                index += 1
                continue

            raise ValueError(
                f"Unsupported cmake configure option: {argument}"
            )

        if not source_seen or not build_seen:
            raise ValueError(
                "CMake configure commands must provide both -S and -B."
            )

        return prepared

    def _prepare_cmake_build_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        if len(argv) < 3:
            raise ValueError(
                "cmake --build requires a build directory."
            )

        prepared = argv.copy()
        build_dir = self._resolve_directory_from_cwd(
            cwd_path,
            prepared[2],
            must_exist=True,
        )
        prepared[2] = str(build_dir)

        index = 3

        while index < len(prepared):
            argument = prepared[index]

            if argument in self.CMAKE_BUILD_VALUE_OPTIONS:
                if index + 1 >= len(prepared):
                    raise ValueError(
                        f"CMake build option '{argument}' requires a value."
                    )
                index += 2
                continue

            raise ValueError(
                f"Unsupported cmake build option: {argument}"
            )

        return prepared

    def _prepare_ctest_command(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        prepared = argv.copy()
        index = 1

        while index < len(prepared):
            argument = prepared[index]

            if argument == "--test-dir":
                if index + 1 >= len(prepared):
                    raise ValueError(
                        "ctest --test-dir requires a directory."
                    )
                directory = self._resolve_directory_from_cwd(
                    cwd_path,
                    prepared[index + 1],
                    must_exist=True,
                )
                prepared[index + 1] = str(directory)
                index += 2
                continue

            if argument in self.CTEST_FLAG_OPTIONS:
                index += 1
                continue

            if argument in self.CTEST_VALUE_OPTIONS:
                if index + 1 >= len(prepared):
                    raise ValueError(
                        f"CTest option '{argument}' requires a value."
                    )
                index += 2
                continue

            if any(
                argument.startswith(prefix)
                for prefix in self.CTEST_PREFIX_OPTIONS
            ):
                index += 1
                continue

            raise ValueError(
                f"Unsupported ctest option: {argument}"
            )

        return prepared

    # ========================================================
    # Workspace executable
    # ========================================================

    def _prepare_workspace_executable(
        self,
        argv: list[str],
        cwd_path: Path,
    ) -> list[str]:
        candidate_name = Path(argv[0]).name

        if candidate_name in self.DISALLOWED_SHELL_EXECUTABLES:
            raise ValueError(
                f"Shell executable is not allowed: {candidate_name}"
            )

        candidate = self._resolve_file_from_cwd(
            cwd_path,
            argv[0],
            must_exist=True,
        )

        prepared = argv.copy()
        prepared[0] = str(candidate)
        return prepared

    # ========================================================
    # Path helpers
    # ========================================================

    def _resolve_path_from_cwd(
        self,
        cwd_path: Path,
        relative_path: str,
        *,
        must_exist: bool,
    ) -> Path:
        if Path(relative_path).is_absolute():
            raise ValueError(
                "Absolute paths are not allowed in command arguments."
            )

        cwd_relative = cwd_path.relative_to(self.workspace.root)
        combined = cwd_relative / relative_path

        return self.workspace.resolve(
            combined,
            must_exist=must_exist,
        )

    def _resolve_file_from_cwd(
        self,
        cwd_path: Path,
        relative_path: str,
        *,
        must_exist: bool,
    ) -> Path:
        target = self._resolve_path_from_cwd(
            cwd_path,
            relative_path,
            must_exist=must_exist,
        )

        if target == self.workspace.root:
            raise ValueError(
                "A command file path cannot refer to the workspace root."
            )

        if target.exists() and target.is_dir():
            raise IsADirectoryError(
                f"Expected a file but found a directory: {relative_path}"
            )

        return target

    def _resolve_directory_from_cwd(
        self,
        cwd_path: Path,
        relative_path: str,
        *,
        must_exist: bool,
    ) -> Path:
        target = self._resolve_path_from_cwd(
            cwd_path,
            relative_path,
            must_exist=must_exist,
        )

        if target.exists() and not target.is_dir():
            raise NotADirectoryError(
                f"Expected a directory: {relative_path}"
            )

        return target

    # ========================================================
    # Compiler helpers
    # ========================================================

    @staticmethod
    def _looks_like_compiler_file(
        argument: str,
    ) -> bool:
        if argument.startswith("-"):
            return False

        suffix = Path(argument).suffix.lower()

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
    def _sanitized_environment() -> dict[str, str]:
        """
        Prevent generated programs from directly inheriting common
        API credentials from the agent process.
        """

        return {
            key: value
            for key, value in os.environ.items()
            if not SensitiveDataPolicy.is_sensitive_env_key(key)
        }

    # ========================================================
    # Output helpers
    # ========================================================

    @classmethod
    def _truncate_output(
        cls,
        output: str,
    ) -> tuple[str, bool]:
        if len(output) <= cls.MAX_OUTPUT_CHARS:
            return output, False

        return (
            output[: cls.MAX_OUTPUT_CHARS]
            + "\n...[output truncated]",
            True,
        )

    @staticmethod
    def _normalize_timeout_output(
        output: str | bytes | None,
    ) -> str:
        if output is None:
            return ""

        if isinstance(output, bytes):
            return output.decode(
                "utf-8",
                errors="replace",
            )

        return output

    @staticmethod
    def _json(payload: dict) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
        )

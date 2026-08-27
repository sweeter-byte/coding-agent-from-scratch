import json
import subprocess
from pathlib import Path


class CommandTools:
    """
    Command execution tools available to the coding agent.

    Commands run locally inside the workspace using subprocess.

    Important:
    This is NOT a real sandbox.
    """

    ALLOWED_EXECUTABLES = {
        "python",
        "python3",
        "py",
        "g++",
        "clang++",
    }

    COMPILERS = {
        "g++",
        "clang++",
    }

    def __init__(
        self,
        workspace: str | Path,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        self.workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ========================================================
    # Path validation
    # ========================================================

    def _safe_path(
        self,
        relative_path: str,
    ) -> Path:
        """
        Convert a relative workspace path into an
        absolute path and prevent path traversal.
        """

        path = Path(
            relative_path
        )

        if path.is_absolute():
            raise ValueError(
                "Absolute paths are not allowed."
            )

        target = (
            self.workspace
            / path
        ).resolve()

        try:
            target.relative_to(
                self.workspace
            )

        except ValueError:
            raise ValueError(
                "Path escapes the workspace."
            )

        return target

    # ========================================================
    # Command preparation
    # ========================================================

    def _prepare_command(
        self,
        argv: list[str],
    ) -> list[str]:
        """
        Allow:

        1. selected compilers / interpreters
        2. executables generated inside workspace

        shell=True is intentionally not used.
        """

        if not argv:
            raise ValueError(
                "argv cannot be empty."
            )

        executable = argv[0]

        # ----------------------------------------------------
        # Known executables
        # ----------------------------------------------------

        if (
            executable
            in self.ALLOWED_EXECUTABLES
        ):
            return argv

        # ----------------------------------------------------
        # Maybe this is a generated executable
        #
        # Example:
        #
        # ./main
        # ----------------------------------------------------

        candidate = self._safe_path(
            executable
        )

        if not candidate.exists():
            raise ValueError(
                "Executable is not allowed "
                "or does not exist: "
                f"{executable}"
            )

        prepared_argv = (
            argv.copy()
        )

        prepared_argv[0] = str(
            candidate
        )

        return prepared_argv

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
        Execute a command inside workspace.

        Example:

        [
            "g++",
            "main.cpp",
            "-o",
            "main"
        ]

        Instead of:

        "g++ main.cpp -o main && ./main"

        This avoids shell=True and keeps command execution
        easier to inspect and control.
        """

        try:
            command = (
                self._prepare_command(
                    argv
                )
            )

            # -----------------------------------------------
            # Limit timeout to a reasonable range
            # -----------------------------------------------

            timeout_seconds = max(
                1,
                min(
                    timeout_seconds,
                    30,
                ),
            )

            # -----------------------------------------------
            # Execute command
            # -----------------------------------------------

            result = subprocess.run(
                command,
                cwd=self.workspace,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )

            stdout = (
                result.stdout or ""
            )

            stderr = (
                result.stderr or ""
            )

            # -----------------------------------------------
            # Prevent huge outputs from filling LLM context
            # -----------------------------------------------

            max_output = 12000

            if len(stdout) > max_output:
                stdout = (
                    stdout[:max_output]
                    + "\n...[stdout truncated]"
                )

            if len(stderr) > max_output:
                stderr = (
                    stderr[:max_output]
                    + "\n...[stderr truncated]"
                )

            return json.dumps(
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
                },
                ensure_ascii=False,
            )

        except subprocess.TimeoutExpired as e:
            return json.dumps(
                {
                    "ok": False,
                    "purpose": purpose,
                    "error": (
                        "Command timed out."
                    ),
                    "stdout": (
                        e.stdout or ""
                    ),
                    "stderr": (
                        e.stderr or ""
                    ),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps(
                {
                    "ok": False,
                    "purpose": purpose,
                    "error": str(e),
                },
                ensure_ascii=False,
            )
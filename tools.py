from pathlib import Path
import json
import subprocess


class LocalTools:
    """
    Local tools available to the coding agent.

    Current version:
    1. write_file
    2. run_command

    No read_file yet.
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

    def __init__(self, workspace: str = "workspace"):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Files created by the agent during THIS run.
        # Existing user files cannot be overwritten.
        self.created_files: set[Path] = set()

    def _safe_path(self, relative_path: str) -> Path:
        """
        Convert a relative workspace path into an absolute path
        and prevent path traversal such as ../../xxx.
        """
        path = Path(relative_path)

        if path.is_absolute():
            raise ValueError("Absolute paths are not allowed.")

        target = (self.workspace / path).resolve()

        try:
            target.relative_to(self.workspace)
        except ValueError:
            raise ValueError("Path escapes the workspace.")

        return target

    def write_file(self, path: str, content: str) -> str:
        """
        Create a new file.

        If the file was created by this agent during the current run,
        rewriting it is allowed so the agent can fix compilation/runtime errors.

        Pre-existing files are never overwritten.
        """
        try:
            target = self._safe_path(path)

            if target.exists() and target not in self.created_files:
                return json.dumps(
                    {
                        "ok": False,
                        "error": f"Refusing to overwrite existing file: {path}",
                    },
                    ensure_ascii=False,
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            self.created_files.add(target)

            return json.dumps(
                {
                    "ok": True,
                    "path": path,
                    "message": f"File written successfully: {path}",
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(e),
                },
                ensure_ascii=False,
            )

    def _prepare_command(self, argv: list[str]) -> list[str]:
        """
        Only allow:
        - selected compilers/interpreters
        - executables generated inside workspace

        We intentionally do NOT use shell=True.
        """
        if not argv:
            raise ValueError("argv cannot be empty.")

        executable = argv[0]

        if executable in self.ALLOWED_EXECUTABLES:
            return argv

        # Maybe this is an executable generated inside workspace,
        # e.g. ./main or main.exe
        candidate = self._safe_path(executable)

        if not candidate.exists():
            raise ValueError(
                f"Executable is not allowed or does not exist: {executable}"
            )

        new_argv = argv.copy()
        new_argv[0] = str(candidate)

        return new_argv

    def run_command(
        self,
        argv: list[str],
        purpose: str,
        stdin: str = "",
        timeout_seconds: int = 20,
    ) -> str:
        """
        Execute a command inside workspace.

        argv example:
            ["g++", "main.cpp", "-o", "main"]

        Instead of:
            "g++ main.cpp -o main && ./main"

        This avoids shell=True and makes execution more controlled.
        """
        try:
            command = self._prepare_command(argv)

            timeout_seconds = max(1, min(timeout_seconds, 30))

            result = subprocess.run(
                command,
                cwd=self.workspace,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )

            stdout = result.stdout
            stderr = result.stderr

            # Avoid feeding extremely large outputs back into the LLM.
            max_output = 12000

            if len(stdout) > max_output:
                stdout = stdout[:max_output] + "\n...[stdout truncated]"

            if len(stderr) > max_output:
                stderr = stderr[:max_output] + "\n...[stderr truncated]"

            return json.dumps(
                {
                    "ok": result.returncode == 0,
                    "purpose": purpose,
                    "argv": argv,
                    "returncode": result.returncode,
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
                    "error": "Command timed out.",
                    "stdout": e.stdout or "",
                    "stderr": e.stderr or "",
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
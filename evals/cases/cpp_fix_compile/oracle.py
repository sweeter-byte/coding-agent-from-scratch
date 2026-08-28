import subprocess
import sys
import tempfile
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
source = workspace / "main.cpp"

with tempfile.TemporaryDirectory() as temp_dir:
    executable = Path(temp_dir) / "program"
    compile_result = subprocess.run(
        ["g++", "-std=c++17", str(source), "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_result.returncode != 0:
        raise SystemExit(compile_result.stderr or "compilation failed")

    run_result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    if run_result.returncode != 0:
        raise SystemExit(run_result.stderr or "program failed")
    assert run_result.stdout.strip() == "8", run_result.stdout

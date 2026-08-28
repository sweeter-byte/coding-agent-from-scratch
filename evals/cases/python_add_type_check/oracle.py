import importlib
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(workspace))
calculator = importlib.import_module("calculator")

assert calculator.add(2, 3) == 5
assert calculator.add(-4, 1) == -3

for args in [(1.5, 2), (1, 2.5), ("1", 2), (1, "2")]:
    try:
        calculator.add(*args)
    except TypeError:
        pass
    else:
        raise AssertionError(f"add{args!r} must raise TypeError")

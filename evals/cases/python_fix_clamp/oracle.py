import importlib
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(workspace))
utils = importlib.import_module("utils")

cases = [
    (5, 0, 10, 5),
    (-2, 0, 10, 0),
    (20, 0, 10, 10),
    (3, 3, 3, 3),
    (-5, -10, -1, -5),
]
for value, lower, upper, expected in cases:
    actual = utils.clamp(value, lower, upper)
    assert actual == expected, (value, lower, upper, actual, expected)

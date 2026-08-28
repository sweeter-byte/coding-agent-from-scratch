import importlib
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(workspace))
module = importlib.import_module("collections_utils")
fn = module.unique_preserve_order

assert fn([]) == []
assert fn([3, 1, 3, 2, 1]) == [3, 1, 2]
assert fn(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
assert fn([1, 1, 1]) == [1]

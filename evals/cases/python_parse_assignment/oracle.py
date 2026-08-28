import importlib
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(workspace))
parser = importlib.import_module("parser")

assert parser.parse_assignment("name=alice") == ("name", "alice")
assert parser.parse_assignment(" token = a=b=c ") == ("token", "a=b=c")
assert parser.parse_assignment("empty=") == ("empty", "")
try:
    parser.parse_assignment("missing")
except ValueError:
    pass
else:
    raise AssertionError("missing '=' must raise ValueError")

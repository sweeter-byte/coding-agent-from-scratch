import pytest

from parser import parse_assignment


def test_parse_simple_assignment():
    assert parse_assignment("name=alice") == ("name", "alice")


def test_parse_requires_equals():
    with pytest.raises(ValueError):
        parse_assignment("name")

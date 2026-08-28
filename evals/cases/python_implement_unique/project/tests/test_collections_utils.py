from collections_utils import unique_preserve_order


def test_unique_preserve_order_basic():
    assert unique_preserve_order([3, 1, 3, 2, 1]) == [3, 1, 2]

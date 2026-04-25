from __future__ import annotations

import pytest

from authentication.hex_utils import normalize_hex_string


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("deadbeef", "deadbeef"),
        ("  DEADBEEF  ", "deadbeef"),
        ("0xDEADBEEF", "deadbeef"),
        ("  0xAbCd  ", "abcd"),
    ],
)
def test_normalize_hex_string_returns_normalized_hex(value: str, expected: str) -> None:
    result = normalize_hex_string(value)

    assert result == expected

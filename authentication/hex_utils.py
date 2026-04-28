from __future__ import annotations


def normalize_hex_string(value: str) -> str:
    """
    Normalize a hexadecimal string for internal use.

    Leading and trailing whitespace is removed, all letters are converted to lowercase,
    and an optional 0x prefix is stripped if present.

    :param value: The hexadecimal string to normalize.
    :returns: The normalized hexadecimal string.
    """

    normalized = value.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    return normalized

from __future__ import annotations


def validate_txid(txid: str) -> str:
    """
    Validate a Bitcoin transaction id and return its trimmed representation.

    A txid must be a non-empty 64-character hexadecimal string.

    :param txid: Bitcoin transaction id.
    :return: Normalized Bitcoin transaction id.
    :raises ValueError: If the txid is not valid.
    """
    if not isinstance(txid, str):
        raise ValueError("txid must be a string.")

    normalized = txid.strip()
    if not normalized:
        raise ValueError("txid must not be empty.")

    if len(normalized) != 64:
        raise ValueError("txid must be a 64-character hexadecimal string.")

    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("txid must be a 64-character hexadecimal string.") from exc

    return normalized

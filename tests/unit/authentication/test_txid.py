from __future__ import annotations

import pytest

from authentication.bitcoin.txid import validate_txid


def test_validate_txid_returns_trimmed_txid_for_valid_value() -> None:
    txid = "ab" * 32

    assert validate_txid(f"  {txid}  ") == txid


def test_validate_txid_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="txid must not be empty"):
        validate_txid("   ")


@pytest.mark.parametrize("txid", ["ab", "g" * 64, "ab" * 31, "ab" * 33])
def test_validate_txid_rejects_non_64_char_hex_values(txid: str) -> None:
    with pytest.raises(
        ValueError,
        match="txid must be a 64-character hexadecimal string",
    ):
        validate_txid(txid)

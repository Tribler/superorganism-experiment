from __future__ import annotations

import pytest

from bitcoin.utils import *


# =========================================================
# validate_txid()
# =========================================================
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


# =========================================================
# validate_raw_tx_hex()
# =========================================================
def test_validate_raw_tx_hex_returns_trimmed_hex_for_valid_value() -> None:
    raw_tx_hex = "deadbeef"

    assert validate_raw_tx_hex(f"  {raw_tx_hex}  ") == raw_tx_hex


@pytest.mark.parametrize("raw_tx_hex", [123, None])
def test_validate_raw_tx_hex_rejects_non_string_input(raw_tx_hex: object) -> None:
    with pytest.raises(ValueError, match="raw_tx_hex must be a string"):
        validate_raw_tx_hex(raw_tx_hex)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw_tx_hex", ["", "   "])
def test_validate_raw_tx_hex_rejects_empty_input(raw_tx_hex: str) -> None:
    with pytest.raises(ValueError, match="raw_tx_hex must not be empty"):
        validate_raw_tx_hex(raw_tx_hex)


@pytest.mark.parametrize("raw_tx_hex", ["zz", "abx1", "0g"])
def test_validate_raw_tx_hex_rejects_non_hex_input(raw_tx_hex: str) -> None:
    with pytest.raises(
        ValueError,
        match="raw_tx_hex must be a hexadecimal string",
    ):
        validate_raw_tx_hex(raw_tx_hex)


# =========================================================
# validate_psbt_base64()
# =========================================================
def test_validate_psbt_base64_returns_trimmed_base64_for_valid_value() -> None:
    psbt_base64 = "cHNidP8BAAoCAAAAAQ=="

    assert validate_psbt_base64(f"  {psbt_base64}  ") == psbt_base64


@pytest.mark.parametrize("psbt_base64", [123, None])
def test_validate_psbt_base64_rejects_non_string_input(psbt_base64: object) -> None:
    with pytest.raises(ValueError, match="psbt_base64 must be a string"):
        validate_psbt_base64(psbt_base64)  # type: ignore[arg-type]


@pytest.mark.parametrize("psbt_base64", ["", "   "])
def test_validate_psbt_base64_rejects_empty_input(psbt_base64: str) -> None:
    with pytest.raises(ValueError, match="psbt_base64 must not be empty"):
        validate_psbt_base64(psbt_base64)


@pytest.mark.parametrize("psbt_base64", ["zz", "not-base64!", "ab==?"])
def test_validate_psbt_base64_rejects_non_base64_input(psbt_base64: str) -> None:
    with pytest.raises(ValueError, match="psbt_base64 must be a base64 string"):
        validate_psbt_base64(psbt_base64)


# =========================================================
# sats_to_btc_string()
# =========================================================
def test_sats_to_btc_string_returns_expected_btc_string_for_valid_amount() -> None:
    assert sats_to_btc_string(12_345_678) == "0.12345678"


def test_sats_to_btc_string_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="amount_sats must be non-negative"):
        sats_to_btc_string(-1)


# =========================================================
# btc_value_to_sats()
# =========================================================
@pytest.mark.parametrize(
    ("btc_value", "expected_sats"),
    [
        (1, 100_000_000),
        (0.1, 10_000_000),
        ("0.00000001", 1),
        (Decimal("1.23456789"), 123_456_789),
    ],
)
def test_btc_value_to_sats_returns_expected_sats_for_valid_values(
    btc_value: int | float | str | Decimal,
    expected_sats: int,
) -> None:
    assert btc_value_to_sats(btc_value) == expected_sats


@pytest.mark.parametrize("btc_value", [-1, "-0.00000001", Decimal("-1")])
def test_btc_value_to_sats_rejects_negative_values(
    btc_value: int | str | Decimal,
) -> None:
    with pytest.raises(ValueError, match="BTC value must be non-negative"):
        btc_value_to_sats(btc_value)


@pytest.mark.parametrize(
    "btc_value",
    ["0.000000001", Decimal("1.000000001"), 1.1e-8],
)
def test_btc_value_to_sats_rejects_values_not_exactly_representable_in_sats(
    btc_value: float | str | Decimal,
) -> None:
    with pytest.raises(
        ValueError,
        match="BTC value is not exactly representable in satoshis",
    ):
        btc_value_to_sats(btc_value)


@pytest.mark.parametrize(
    "btc_value",
    [True, "abc", None, Decimal("NaN"), Decimal("Infinity"), float("inf")],
)
def test_btc_value_to_sats_rejects_invalid_values(
    btc_value: object,
) -> None:
    with pytest.raises(ValueError, match="Invalid BTC value"):
        btc_value_to_sats(btc_value)  # type: ignore[arg-type]

from __future__ import annotations

import base64
import binascii

from decimal import Decimal, ROUND_DOWN, InvalidOperation

SATOSHIS_PER_BTC = Decimal("100000000")


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


def validate_raw_tx_hex(raw_tx_hex: str) -> str:
    """
    Validate a serialized raw transaction hex string.

    A raw transaction must be a non-empty hexadecimal string. The returned value is
    trimmed of surrounding whitespace.

    :param raw_tx_hex: Raw transaction hex.
    :returns: Normalized raw transaction hex.
    :raises ValueError: If the value is not a valid non-empty hexadecimal string.
    """
    if not isinstance(raw_tx_hex, str):
        raise ValueError("raw_tx_hex must be a string.")

    normalized = raw_tx_hex.strip()
    if not normalized:
        raise ValueError("raw_tx_hex must not be empty.")

    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("raw_tx_hex must be a hexadecimal string.") from exc

    return normalized


def validate_psbt_base64(psbt_base64: str) -> str:
    """
    Validate a base64-encoded PSBT string.

    The returned value is trimmed of surrounding whitespace.

    :param psbt_base64: PSBT base64 string.
    :returns: Normalized PSBT base64 string.
    :raises ValueError: If the value is not a valid non-empty base64 string.
    """
    if not isinstance(psbt_base64, str):
        raise ValueError("psbt_base64 must be a string.")

    normalized = psbt_base64.strip()
    if not normalized:
        raise ValueError("psbt_base64 must not be empty.")

    try:
        base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("psbt_base64 must be a base64 string.") from exc

    return normalized


def sats_to_btc_string(amount_sats: int) -> str:
    """
    Convert an amount in satoshis to a Bitcoin-denominated decimal string.

    The returned value is formatted with exactly 8 decimal places, which is the
    standard precision used for BTC amounts in Bitcoin RPC calls.

    :param amount_sats: The amount in satoshis. Must be non-negative.
    :return: A string representing the equivalent BTC amount.
    :raises ValueError: If amount_sats is negative.
    """
    if amount_sats < 0:
        raise ValueError("amount_sats must be non-negative.")

    btc = (Decimal(amount_sats) / SATOSHIS_PER_BTC).quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN,
    )
    return format(btc, "f")


def btc_value_to_sats(btc_value: int | float | str | Decimal) -> int:
    """
    Convert a BTC value to satoshis.

    Validates that the BTC value is finite, non-negative, and exactly epresentable as a
    whole number of satoshis.

    :param btc_value: The BTC value to convert.
    :returns: The equivalent value in satoshis.
    :raises ValueError: If btc_value is invalid, not finite, negative, or not exactly
                        representable as a whole number of satoshis.
    """
    if isinstance(btc_value, bool):
        raise ValueError("Invalid BTC value.")

    try:
        if isinstance(btc_value, Decimal):
            value = btc_value
        elif isinstance(btc_value, float):
            value = Decimal(str(btc_value))
        else:
            value = Decimal(btc_value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid BTC value.") from exc

    if not value.is_finite():
        raise ValueError("Invalid BTC value.")

    if value < 0:
        raise ValueError("BTC value must be non-negative.")

    sats_decimal = value * SATOSHIS_PER_BTC
    if sats_decimal != sats_decimal.to_integral_value():
        raise ValueError("BTC value is not exactly representable in satoshis.")

    return int(sats_decimal)

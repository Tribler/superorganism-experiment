from __future__ import annotations

from authentication.hex_utils import normalize_hex_string


def _decode_ed25519_key_hex(
    key_hex: str,
    *,
    key_label: str,
    error_type: type[ValueError],
) -> bytes:
    """
    Normalize, decode, and validate an Ed25519 key from hexadecimal form.

    The input is first normalized as a hex string, then decoded to bytes and checked to
    ensure it is exactly 32 bytes long, as required for Ed25519 keys.

    :param key_hex: The hexadecimal key representation to decode.
    :param key_label: A human-readable label used in validation error messages.
    :param error_type: The ValueError subclass to raise on validation failure.
    :returns: The decoded 32-byte Ed25519 key.
    :raises ValueError: If the key is not valid hexadecimal or is not exactly
                        32 bytes long.
    """
    normalized = normalize_hex_string(key_hex)

    try:
        key_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise error_type(f"{key_label} must be a valid hex string.") from exc

    if len(key_bytes) != 32:
        raise error_type(
            f"Ed25519 {key_label.lower()} must be exactly 32 bytes (64 hex characters)."
        )

    return key_bytes

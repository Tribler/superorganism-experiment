from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization

from authentication.crypto.ed25519_message_signer import (
    Ed25519MessageSigner,
    InvalidPrivateKeyFormatError,
)
from authentication.crypto.ed25519_signature_verifier import Ed25519SignatureVerifier


# =========================================================
# from_private_key_hex()
# =========================================================
def test_from_private_key_hex_returns_signer_for_valid_key() -> None:
    signer = Ed25519MessageSigner.from_private_key_hex("0x" + ("11" * 32))

    private_key_bytes = signer._private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    assert private_key_bytes.hex() == "11" * 32


@pytest.mark.parametrize(
    ("private_key_hex", "expected_message"),
    [
        ("zz", "Private key must be a valid hex string."),
        ("11" * 31, "Ed25519 private key must be exactly 32 bytes"),
        ("11" * 33, "Ed25519 private key must be exactly 32 bytes"),
    ],
)
def test_from_private_key_hex_rejects_invalid_private_key_format(
    private_key_hex: str,
    expected_message: str,
) -> None:
    with pytest.raises(InvalidPrivateKeyFormatError, match=expected_message):
        Ed25519MessageSigner.from_private_key_hex(private_key_hex)


# =========================================================
# sign_message()
# =========================================================
def test_sign_message_returns_signature_verifiable_by_ed25519_verifier() -> None:
    signer = Ed25519MessageSigner.from_private_key_hex("11" * 32)
    message = b"hello"

    signature = signer.sign_message(message)
    public_key_hex = (
        signer._private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    verifier = Ed25519SignatureVerifier.from_public_key_hex(public_key_hex)

    result = verifier.verify_signature(
        message=message,
        signature=signature,
    )

    assert result is True


def test_sign_message_rejects_non_bytes_message() -> None:
    signer = Ed25519MessageSigner.from_private_key_hex("11" * 32)

    with pytest.raises(TypeError, match="message must be bytes"):
        signer.sign_message("hello")  # type: ignore[arg-type]

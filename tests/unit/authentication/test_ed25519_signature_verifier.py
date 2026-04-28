from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization

from authentication.crypto.ed25519_message_signer import Ed25519MessageSigner
from authentication.crypto.ed25519_signature_verifier import (
    Ed25519SignatureVerifier,
    InvalidPublicKeyFormatError,
)


# =========================================================
# from_public_key_hex()
# =========================================================
def test_from_public_key_hex_returns_verifier_for_valid_key() -> None:
    verifier = Ed25519SignatureVerifier.from_public_key_hex("0x" + ("AB" * 32))

    public_key_bytes = verifier._public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    assert public_key_bytes.hex() == "ab" * 32


@pytest.mark.parametrize(
    ("public_key_hex", "expected_message"),
    [
        ("zz", "Public key must be a valid hex string."),
        ("ab" * 31, "Ed25519 public key must be exactly 32 bytes"),
        ("ab" * 33, "Ed25519 public key must be exactly 32 bytes"),
    ],
)
def test_from_public_key_hex_rejects_invalid_public_key_format(
    public_key_hex: str,
    expected_message: str,
) -> None:
    with pytest.raises(InvalidPublicKeyFormatError, match=expected_message):
        Ed25519SignatureVerifier.from_public_key_hex(public_key_hex)


# =========================================================
# verify_signature()
# =========================================================
def test_verify_signature_returns_true_for_valid_signature() -> None:
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


def test_verify_signature_returns_false_for_invalid_signature() -> None:
    signer = Ed25519MessageSigner.from_private_key_hex("11" * 32)
    wrong_signature = signer.sign_message(b"other-message")
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
        message=b"hello",
        signature=wrong_signature,
    )

    assert result is False

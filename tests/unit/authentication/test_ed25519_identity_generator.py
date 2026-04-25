from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authentication.crypto.ed25519_message_signer import Ed25519MessageSigner
from authentication.crypto.ed25519_signature_verifier import Ed25519SignatureVerifier
from authentication.identity.ed25519_identity_generator import Ed25519IdentityGenerator
from authentication.registration_commitment_utils import compute_registration_commitment


# =========================================================
# generate_identity()
# =========================================================
def test_generate_identity_returns_key_pair_that_can_sign_and_verify() -> None:
    generator = Ed25519IdentityGenerator()
    identity = generator.generate_identity()
    signer = Ed25519MessageSigner.from_private_key_hex(identity.private_key_hex)
    verifier = Ed25519SignatureVerifier.from_public_key_hex(identity.public_key_hex)
    message = b"hello"

    signature = signer.sign_message(message)
    result = verifier.verify_signature(
        message=message,
        signature=signature,
    )

    assert result is True

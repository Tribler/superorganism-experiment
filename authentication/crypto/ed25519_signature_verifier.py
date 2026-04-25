from __future__ import annotations

from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from authentication.crypto.ed25519_key_utils import _decode_ed25519_key_hex
from authentication.crypto.signature_verifier import SignatureVerifier


class InvalidPublicKeyFormatError(ValueError):
    pass


@dataclass
class Ed25519SignatureVerifier(SignatureVerifier):
    """
    Message verifier implementation backed by an Ed25519 public key.

    This class verifies Ed25519 signatures and can be constructed directly from a public
    key object or from a hexadecimal public key representation.
    """

    _public_key: Ed25519PublicKey

    @classmethod
    def from_public_key_hex(cls, public_key_hex: str) -> "Ed25519SignatureVerifier":
        """
        Create a signature verifier from a hexadecimal Ed25519 public key.

        The provided key is normalized, decoded from hexadecimal, and validated to ensure
        it is exactly 32 bytes long before constructing the signer.

        :param public_key_hex: The Ed25519 public key as a hex string.
        :returns: A signer initialized with the given public key.
        :raises InvalidPublicKeyFormatError: If the key is not valid hexadecimal or does
                                             not represent exactly 32 bytes.
        """
        public_key_bytes = _decode_ed25519_key_hex(
            public_key_hex,
            key_label="Public key",
            error_type=InvalidPublicKeyFormatError,
        )
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        return cls(_public_key=public_key)

    def verify_signature(
        self,
        message: bytes,
        signature: bytes,
    ) -> bool:
        """
        Verify that a signature is valid for the given message and bound public key.

        :param message: The message whose signature should be verified.
        :param signature: The signature to verify.
        :returns: True if the signature is valid, otherwise False.
        """
        try:
            self._public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

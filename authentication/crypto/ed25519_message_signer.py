from __future__ import annotations

from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authentication.crypto.ed25519_key_utils import _decode_ed25519_key_hex
from authentication.crypto.message_signer import MessageSigner


class InvalidPrivateKeyFormatError(ValueError):
    pass


@dataclass
class Ed25519MessageSigner(MessageSigner):
    """
    Message signer implementation backed by an Ed25519 private key.

    This class creates Ed25519 signatures for byte messages and can be
    constructed directly from a private key object or from a hexadecimal
    private key representation.
    """

    _private_key: Ed25519PrivateKey

    @classmethod
    def from_private_key_hex(cls, private_key_hex: str) -> "Ed25519MessageSigner":
        """
        Create a signer from a hexadecimal Ed25519 private key.

        The provided key is normalized, decoded from hexadecimal, and validated to ensure
        it is exactly 32 bytes long before constructing the signer.

        :param private_key_hex: The Ed25519 private key as a hex string.
        :returns: A signer initialized with the given private key.
        :raises InvalidPrivateKeyFormatError: If the key is not valid hexadecimal or does
                                              not represent exactly 32 bytes.
        """
        private_key_bytes = _decode_ed25519_key_hex(
            private_key_hex,
            key_label="Private key",
            error_type=InvalidPrivateKeyFormatError,
        )
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        return cls(_private_key=private_key)

    def sign_message(self, message: bytes) -> bytes:
        """
        Sign a message using the underlying private key.

        :param message: The message bytes to sign.
        :returns: The resulting signature bytes.
        :raises TypeError: If message is not of type bytes.
        """
        if not isinstance(message, bytes):
            raise TypeError("message must be bytes.")
        return self._private_key.sign(message)

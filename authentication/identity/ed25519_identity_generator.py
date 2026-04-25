from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authentication.identity.identity_generator import IdentityGenerator
from authentication.identity.models import ApplicationIdentity
from authentication.registration_commitment_utils import compute_registration_commitment


class Ed25519IdentityGenerator(IdentityGenerator):
    """Identity generator that creates application identities from Ed25519 key pairs."""

    def generate_identity(self) -> ApplicationIdentity:
        """
        Generate a new application identity based on a fresh Ed25519 key pair.

        This method creates a new Ed25519 private/public key pair, serializes both keys to
        raw hexadecimal form, computes the registration commitment from the public key
        bytes, and returns the resulting identity bundle.

        :returns: A newly generated application identity.
        """
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        private_key_hex = private_key_bytes.hex()
        public_key_hex = public_key_bytes.hex()

        registration_commitment_hex = compute_registration_commitment(public_key_bytes)

        return ApplicationIdentity(
            public_key_hex=public_key_hex,
            private_key_hex=private_key_hex,
            registration_commitment_hex=registration_commitment_hex,
        )

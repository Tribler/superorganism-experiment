from __future__ import annotations

import hashlib

from authentication.constants import REGISTRATION_PROTOCOL_LABEL
from config import NETWORK_ID


def compute_registration_commitment(public_key_bytes: bytes) -> str:
    """
    Compute the registration commitment for a public key.

    The commitment is the SHA-256 hash of the protocol label, network identifier, and
    public key bytes concatenated together, returned as a lowercase hexadecimal string.

    :param public_key_bytes: The raw public key bytes to commit to.
    :returns: The registration commitment as a hexadecimal digest string.
    """
    digest = hashlib.sha256(
        REGISTRATION_PROTOCOL_LABEL + NETWORK_ID + public_key_bytes
    ).hexdigest()
    return digest

from __future__ import annotations

from typing import Protocol


class SignatureVerifier(Protocol):
    """Interface for verifying signatures against a bound public key."""

    def verify_signature(
        self,
        message: bytes,
        signature: bytes,
    ) -> bool: ...

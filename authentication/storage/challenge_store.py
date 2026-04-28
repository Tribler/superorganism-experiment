from __future__ import annotations

from typing import Protocol

from authentication.models.authentication_models import StoredChallenge


class ChallengeStore(Protocol):
    """Interface for storing and retrieving authentication challenges by public key."""

    def save(self, challenge: StoredChallenge) -> None: ...

    def get(self, public_key_hex: str) -> StoredChallenge | None: ...

    def delete(self, public_key_hex: str) -> None: ...

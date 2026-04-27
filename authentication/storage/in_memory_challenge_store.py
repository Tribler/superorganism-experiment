from __future__ import annotations

from authentication.models.authentication_models import StoredChallenge
from authentication.storage.challenge_store import ChallengeStore


class ChallengeStoreFullError(RuntimeError):
    """Raised when the in-memory challenge store cannot accept more active challenges."""


class InMemoryChallengeStore(ChallengeStore):
    """
    In-memory implementation of ChallengeStore for storing challenges.

    Challenges are indexed by public key, automatically discarded when expired on access
    or cleanup, and subject to a configurable maximum store size.
    """

    def __init__(self, max_size: int = 50) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero.")

        self._challenges: dict[str, StoredChallenge] = {}
        self._max_size = max_size

    def save(self, challenge: StoredChallenge) -> None:
        """
        Store a challenge in the in-memory challenge store.

        If the challenge is new and the store has reached its maximum size, expired
        entries are removed before checking capacity again. If the store is still full
        after cleanup, a ChallengeStoreFullError is raised. An existing challenge with the
        same public key is overwritten.

        :param challenge: The challenge to store.
        :raises ChallengeStoreFullError: If the store is full and no space can be
                                         freed by removing expired challenges.
        """
        if (
            challenge.public_key_hex not in self._challenges
            and len(self._challenges) >= self._max_size
        ):
            self._cleanup_expired()
            if len(self._challenges) >= self._max_size:
                raise ChallengeStoreFullError(
                    f"Challenge store is full (max_size={self._max_size})."
                )

        self._challenges[challenge.public_key_hex] = challenge

    def get(self, public_key_hex: str) -> StoredChallenge | None:
        """
        Retrieve the stored challenge for the given public key if it exists and is still
        valid.

        If the stored challenge has expired, it is removed from the in-memory store and
        None is returned.

        :param public_key_hex: The public key whose stored challenge should be retrieved.
        :returns: The stored challenge if present and not expired, otherwise None.
        """
        challenge = self._challenges.get(public_key_hex)
        if challenge is None:
            return None

        if challenge.is_expired():
            del self._challenges[public_key_hex]
            return None

        return challenge

    def delete(self, public_key_hex: str) -> None:
        """
        Remove the stored challenge for the given public key, if present.

        :param public_key_hex: The public key whose stored challenge should be removed.
        :returns: None.
        """
        self._challenges.pop(public_key_hex, None)

    def _cleanup_expired(self) -> None:
        """
        Remove all expired challenges from the in-memory challenge store.

        :returns: None.
        """
        for public_key_hex, challenge in list(self._challenges.items()):
            if challenge.is_expired():
                del self._challenges[public_key_hex]

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from authentication.constants import AUTHENTICATION_CHALLENGE_TTL_SECONDS


@dataclass
class StoredChallenge:
    """Stored authentication challenge together with its public key and issuance time."""

    public_key_hex: str
    message: str
    issued_at: datetime

    def is_expired(self) -> bool:
        """
        Check whether this challenge has expired.

        A challenge is considered expired once the current UTC time is later than its
        issuance time plus the configured authentication challenge lifetime.

        :returns: True if the challenge has expired, otherwise False.
        """
        return datetime.now(timezone.utc) > self.issued_at + timedelta(
            seconds=AUTHENTICATION_CHALLENGE_TTL_SECONDS)

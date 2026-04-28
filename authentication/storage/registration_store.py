from __future__ import annotations

from typing import Protocol

from authentication.models.registration_models import StoredRegistration


class RegistrationStore(Protocol):
    """Interface for storing and retrieving persisted registration records."""

    def get(self, public_key_hex: str) -> StoredRegistration | None: ...

    def save(self, registration: StoredRegistration) -> None: ...

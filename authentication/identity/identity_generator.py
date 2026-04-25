from typing import Protocol

from authentication.identity.models import ApplicationIdentity


class IdentityGenerator(Protocol):
    """Abstraction for identity generation across signature schemes."""

    def generate_identity(self) -> ApplicationIdentity: ...

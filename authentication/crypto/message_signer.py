from __future__ import annotations

from typing import Protocol


class MessageSigner(Protocol):
    """Interface for signing messages."""

    def sign_message(self, message: bytes) -> bytes: ...

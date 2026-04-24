from __future__ import annotations

from typing import Protocol

from authentication.transaction_verification.models import (
    TransactionVerificationRequest,
    TransactionVerificationResult,
)


class TransactionVerifier(Protocol):
    """Structural interface for transaction verification backends."""

    def verify(
        self,
        request: TransactionVerificationRequest,
    ) -> TransactionVerificationResult: ...

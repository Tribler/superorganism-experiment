from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransactionVerificationRequest:
    """Input data required to verify a registration transaction."""

    txid: str
    expected_treasury_address: str
    expected_fee_sats: int
    expected_registration_commitment: str


@dataclass(frozen=True, slots=True)
class TransactionVerificationResult:
    """Result of verifying a registration transaction."""

    success: bool
    reason: str | None = None
    amount_paid_sats: int | None = None
    confirmations: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedTxOutput:
    """Normalized representation of a transaction output."""

    value_sats: int
    address: str | None
    script_hex: str


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    """Normalized representation of a transaction used for verification."""

    txid: str
    confirmations: int
    outputs: list[NormalizedTxOutput]

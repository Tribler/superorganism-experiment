from __future__ import annotations

import hashlib

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from bitcoin.utils import validate_psbt_base64, validate_txid
from democracy.constants import FUNDING_PROTOCOL_LABEL


def _length_prefix(value: bytes) -> bytes:
    """
    Prefix a byte string with its length.

    Encodes the length as a four-byte unsigned big-endian integer and prepends it
    to the original value.

    :param value: The byte string to prefix.
    :returns: The length-prefixed byte string.
    """
    return len(value).to_bytes(4, "big", signed=False) + value


@dataclass(frozen=True)
class FundingCampaign:
    """
    Immutable funding campaign for a proposed solution.

    A funding campaign defines the amount of Bitcoin funding requested for a solution, the
    payout address of the developer, and the block height by which the campaign should be
    completed. The asking price and deadline height are validated during initialization.
    """

    solution_id: UUID
    solution_hash: str
    developer_payout_address: str
    asking_price_sats: int
    deadline_height: int
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.asking_price_sats <= 0:
            raise ValueError("asking_price_sats must be positive.")

        if self.deadline_height <= 0:
            raise ValueError("deadline_height must be positive.")

    def compute_campaign_commitment_hex(self, network_id: bytes) -> str:
        """
        Compute the campaign commitment as a lowercase hexadecimal digest.

        Builds the canonical campaign commitment from the funding protocol label, network
        identifier, campaign fields, solution fields, payout address, asking price, and
        deadline height. Variable-length fields are length-prefixed before hashing to keep
        the encoded payload unambiguous.

        :param network_id: The network identifier to bind the commitment to.
        :returns: The campaign commitment as a hexadecimal SHA-256 digest.
        :raises ValueError: If network_id is not non-empty bytes.
        """
        if not isinstance(network_id, bytes) or not network_id:
            raise ValueError("network_id must be non-empty bytes.")

        solution_hash_bytes = bytes.fromhex(self.solution_hash)
        payout_address_bytes = self.developer_payout_address.encode("utf-8")

        digest = hashlib.sha256(
            FUNDING_PROTOCOL_LABEL
            + network_id
            + self.id.bytes
            + self.solution_id.bytes
            + _length_prefix(solution_hash_bytes)
            + _length_prefix(payout_address_bytes)
            + self.asking_price_sats.to_bytes(8, "big", signed=False)
            + self.deadline_height.to_bytes(8, "big", signed=False)
        ).hexdigest()

        return digest


@dataclass(frozen=True)
class FundingPledge:
    """
    Immutable funding pledge created by a pledger for a campaign.

    A funding pledge links a pledger to a specific campaign and records the signed PSBT
    that represents the pledged funds. The transaction ID and signed PSBT are validated
    during initialization, and the pledged value and output index must be valid.
    """

    campaign_id: UUID
    pledger_id: UUID
    txid: str
    vout: int
    value_sats: int
    signed_pledge_psbt: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "txid", validate_txid(self.txid))
        object.__setattr__(
            self,
            "signed_pledge_psbt",
            validate_psbt_base64(self.signed_pledge_psbt),
        )

        if self.value_sats <= 0:
            raise ValueError("value_sats must be positive.")
        if self.vout < 0:
            raise ValueError("vout must be non-negative.")

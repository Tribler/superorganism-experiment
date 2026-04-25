from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationIdentity:
    public_key_hex: str
    private_key_hex: str
    registration_commitment_hex: str

from __future__ import annotations

from dataclasses import dataclass

from authentication.registration_commitment_utils import compute_registration_commitment


@dataclass(frozen=True)
class ApplicationIdentity:
    public_key_hex: str
    private_key_hex: str

    @property
    def registration_commitment_hex(self) -> str:
        public_key_bytes = bytes.fromhex(self.public_key_hex)
        return compute_registration_commitment(public_key_bytes)

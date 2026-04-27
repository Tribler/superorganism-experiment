from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StoredRegistration:
    """
    Persisted registration record containing a key-pair, transaction ID, and registration
    time.
    """
    public_key_hex: str
    private_key_hex: str
    txid: str
    registered_at: datetime

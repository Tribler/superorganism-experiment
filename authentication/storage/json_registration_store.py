from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from authentication.models.registration_models import StoredRegistration
from authentication.storage.registration_store import RegistrationStore


class JsonRegistrationStore(RegistrationStore):
    """
    Stores registration records as JSON.

    This is a very non-permanent solution, so it is not tested and all calls should be
    made through the interface RegistrationStore.
    """

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._file_path.exists():
            self._write_all({})

    def get(self, public_key_hex: str) -> StoredRegistration | None:
        data = self._read_all()
        raw = data.get(public_key_hex)

        if raw is None:
            return None

        return StoredRegistration(
            public_key_hex=str(raw["public_key_hex"]),
            private_key_hex=str(raw["private_key_hex"]),
            txid=str(raw["txid"]),
            registered_at=datetime.fromisoformat(str(raw["registered_at"])),
        )

    def save(self, registration: StoredRegistration) -> None:
        data = self._read_all()
        data[registration.public_key_hex] = {
            "public_key_hex": registration.public_key_hex,
            "private_key_hex": registration.private_key_hex,
            "txid": registration.txid,
            "registered_at": registration.registered_at.isoformat(),
        }
        self._write_all(data)

    def _read_all(self) -> dict[str, dict]:
        if not self._file_path.exists():
            return {}

        with self._file_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            raise ValueError("Registration store file has invalid format.")

        return raw

    def _write_all(self, data: dict[str, dict]) -> None:
        temp_path = self._file_path.with_suffix(self._file_path.suffix + ".tmp")

        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

        temp_path.replace(self._file_path)

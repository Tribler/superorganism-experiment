from __future__ import annotations

from datetime import datetime, timezone

import pytest

from authentication.services import authentication_service as authentication_service_module
from authentication.services.authentication_service import AuthenticationService


# =========================================================
# _build_message()
# =========================================================
def test_build_message_decodes_byte_labels_for_signed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authentication_service_module,
        "AUTHENTICATION_PROTOCOL_LABEL",
        b"test-auth-v9",
    )
    monkeypatch.setattr(
        authentication_service_module,
        "NETWORK_ID",
        b"testnet-x",
    )

    message = AuthenticationService._build_message(
        public_key_hex="ab" * 32,
        nonce="nonce-123",
        issued_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert message == "\n".join(
        [
            "protocol=test-auth-v9",
            "network=testnet-x",
            "action=login",
            f"public_key_hex={'ab' * 32}",
            "nonce=nonce-123",
            "issued_at=2026-01-02T03:04:05+00:00",
        ]
    )

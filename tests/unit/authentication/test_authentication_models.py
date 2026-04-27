from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from authentication import models as auth_models
from authentication.models.authentication_models import StoredChallenge


def make_challenge(*, issued_at: datetime) -> StoredChallenge:
    return StoredChallenge(
        public_key_hex="0x1234567890abcdef1234567890abcdef12345678",
        message="Sign this message.",
        issued_at=issued_at,
    )


def test_is_expired_returns_false_before_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_models.authentication_models,
        "AUTHENTICATION_CHALLENGE_TTL_SECONDS",
        120,
    )
    challenge = make_challenge(
        issued_at=datetime.now(timezone.utc) - timedelta(seconds=90),
    )

    assert challenge.is_expired() is False


def test_is_expired_returns_true_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_models.authentication_models,
        "AUTHENTICATION_CHALLENGE_TTL_SECONDS",
        120,
    )
    challenge = make_challenge(
        issued_at=datetime.now(timezone.utc) - timedelta(seconds=150),
    )

    assert challenge.is_expired() is True

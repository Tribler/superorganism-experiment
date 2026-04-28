from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from authentication import models as auth_models
from authentication.models.authentication_models import StoredChallenge
from authentication.storage.in_memory_challenge_store import (
    ChallengeStoreFullError,
    InMemoryChallengeStore,
)


def make_challenge(
    public_key_hex: str = "0x1234567890abcdef1234567890abcdef12345678",
    *,
    message: str = "Sign this message.",
    issued_at: datetime | None = None,
) -> StoredChallenge:
    return StoredChallenge(
        public_key_hex=public_key_hex.lower(),
        message=message,
        issued_at=datetime.now(timezone.utc) if issued_at is None else issued_at,
    )


# =========================================================
# save()
# =========================================================
def test_save_overwrites_existing_challenge_for_same_identity() -> None:
    store = InMemoryChallengeStore()
    public_key_hex = "0x1234567890abcdef1234567890abcdef12345678"

    first = make_challenge(public_key_hex=public_key_hex, message="first")
    second = make_challenge(public_key_hex=public_key_hex, message="second")

    store.save(first)
    store.save(second)

    retrieved = store.get(public_key_hex)

    assert retrieved is not None
    assert retrieved.message == second.message


def test_save_removes_expired_challenges_when_store_is_at_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_models.authentication_models, "AUTHENTICATION_CHALLENGE_TTL_SECONDS", 300
    )
    store = InMemoryChallengeStore(max_size=2)
    now = datetime.now(timezone.utc)

    expired_challenge = make_challenge(
        public_key_hex="0x3333333333333333333333333333333333333333",
        issued_at=now - timedelta(minutes=10),
    )
    active_challenge = make_challenge(
        public_key_hex="0x4444444444444444444444444444444444444444",
        issued_at=now,
    )
    new_challenge = make_challenge(
        public_key_hex="0x5555555555555555555555555555555555555555",
        issued_at=now,
    )

    store.save(expired_challenge)
    store.save(active_challenge)
    store.save(new_challenge)

    assert store.get(expired_challenge.public_key_hex) is None
    assert store.get(active_challenge.public_key_hex) is not None
    assert store.get(new_challenge.public_key_hex) is not None


def test_save_raises_when_store_is_full_of_active_challenges() -> None:
    store = InMemoryChallengeStore(max_size=2)
    now = datetime.now(timezone.utc)

    first = make_challenge(
        public_key_hex="0x6666666666666666666666666666666666666666",
        issued_at=now,
    )
    second = make_challenge(
        public_key_hex="0x7777777777777777777777777777777777777777",
        issued_at=now,
    )
    third = make_challenge(
        public_key_hex="0x8888888888888888888888888888888888888888",
        issued_at=now,
    )

    store.save(first)
    store.save(second)

    try:
        store.save(third)
        assert False, "Expected ChallengeStoreFullError to be raised."
    except ChallengeStoreFullError:
        pass

    assert store.get(first.public_key_hex) is not None
    assert store.get(second.public_key_hex) is not None
    assert store.get(third.public_key_hex) is None


def test_save_overwrites_existing_key_even_when_store_is_at_capacity() -> None:
    store = InMemoryChallengeStore(max_size=1)
    public_key_hex = "0x9999999999999999999999999999999999999999"

    first = make_challenge(public_key_hex=public_key_hex, message="first")
    second = make_challenge(public_key_hex=public_key_hex, message="second")

    store.save(first)
    store.save(second)

    retrieved = store.get(public_key_hex)

    assert retrieved is not None
    assert retrieved.message == "second"


def test_save_and_get_returns_same_challenge() -> None:
    store = InMemoryChallengeStore()
    challenge = make_challenge()

    store.save(challenge)
    retrieved = store.get(challenge.public_key_hex)

    assert retrieved is not None
    assert retrieved.public_key_hex == challenge.public_key_hex
    assert retrieved.message == challenge.message
    assert retrieved.issued_at == challenge.issued_at


# =========================================================
# get()
# =========================================================
def test_get_returns_none_for_unknown_identity() -> None:
    store = InMemoryChallengeStore()

    retrieved = store.get("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd")

    assert retrieved is None


def test_get_returns_none_and_removes_expired_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_models.authentication_models, "AUTHENTICATION_CHALLENGE_TTL_SECONDS", 300
    )
    store = InMemoryChallengeStore()
    expired_challenge = make_challenge(
        public_key_hex="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        issued_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )

    store.save(expired_challenge)

    retrieved = store.get(expired_challenge.public_key_hex)

    assert retrieved is None
    assert expired_challenge.public_key_hex not in store._challenges


# =========================================================
# delete()
# =========================================================
def test_delete_removes_existing_challenge() -> None:
    store = InMemoryChallengeStore()
    challenge = make_challenge()

    store.save(challenge)
    store.delete(challenge.public_key_hex)

    retrieved = store.get(challenge.public_key_hex)
    assert retrieved is None


def test_delete_unknown_identity_does_not_fail() -> None:
    store = InMemoryChallengeStore()

    store.delete("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd")

    assert store.get("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd") is None


# =========================================================
# verify_signature()
# =========================================================
def test_cleanup_expired_removes_expired_and_keeps_active_challenges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_models.authentication_models, "AUTHENTICATION_CHALLENGE_TTL_SECONDS", 300
    )
    store = InMemoryChallengeStore()
    now = datetime.now(timezone.utc)

    expired_challenge = make_challenge(
        public_key_hex="0x1111111111111111111111111111111111111111",
        issued_at=now - timedelta(minutes=10),
    )
    active_challenge = make_challenge(
        public_key_hex="0x2222222222222222222222222222222222222222",
        issued_at=now,
    )

    store.save(expired_challenge)
    store.save(active_challenge)

    store._cleanup_expired()

    assert store.get(expired_challenge.public_key_hex) is None
    assert store.get(active_challenge.public_key_hex) is not None

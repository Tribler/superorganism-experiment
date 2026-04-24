from __future__ import annotations

import pytest

from authentication import constants as tx_constants
from authentication.transaction_verification.base_verifier import BaseVerifier
from authentication.transaction_verification.exceptions import TransactionFetchError
from authentication.transaction_verification.models import (
    NormalizedTransaction,
    NormalizedTxOutput,
    TransactionVerificationRequest,
)


class DummyBaseVerifier(BaseVerifier):
    def __init__(
        self,
        tx: NormalizedTransaction | None = None,
        error: Exception | None = None,
    ) -> None:
        self._tx = tx
        self._error = error

    def _fetch_transaction(self, txid: str) -> NormalizedTransaction | None:
        if self._error is not None:
            raise self._error
        return self._tx


def make_request(
    *,
    txid: str = "txid",
    treasury_address: str = "bc1qtarget",
    fee_sats: int = 50,
    registration_commitment: str = "deadbeef",
) -> TransactionVerificationRequest:
    return TransactionVerificationRequest(
        txid=txid,
        expected_treasury_address=treasury_address,
        expected_fee_sats=fee_sats,
        expected_registration_commitment=registration_commitment,
    )


def make_tx(
    *,
    confirmations: int = 1,
    outputs: list[NormalizedTxOutput] | None = None,
) -> NormalizedTransaction:
    return NormalizedTransaction(
        txid="txid",
        confirmations=confirmations,
        outputs=(
            outputs
            if outputs is not None
            else [
                NormalizedTxOutput(
                    value_sats=50,
                    address="bc1qtarget",
                    script_hex="0014aaaa",
                ),
                NormalizedTxOutput(
                    value_sats=0,
                    address=None,
                    script_hex="6a04deadbeef",
                ),
            ]
        ),
    )


# =========================================================
# verify()
# =========================================================
def test_verify_returns_not_found_when_fetch_returns_none() -> None:
    verifier = DummyBaseVerifier(tx=None)

    result = verifier.verify(make_request())

    assert result.success is False
    assert result.reason == "Transaction not found."
    assert result.amount_paid_sats is None
    assert result.confirmations is None


def test_verify_returns_fetch_error_reason_when_fetch_fails() -> None:
    verifier = DummyBaseVerifier(error=TransactionFetchError("backend unavailable"))

    result = verifier.verify(make_request())

    assert result.success is False
    assert result.reason == "Transaction verification failed: backend unavailable"
    assert result.amount_paid_sats is None
    assert result.confirmations is None


def test_verify_rejects_transaction_below_confirmation_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tx_constants, "MIN_CONFIRMATIONS", 2)
    verifier = DummyBaseVerifier(tx=make_tx(confirmations=1))

    result = verifier.verify(make_request())

    assert result.success is False
    assert result.reason == "Transaction does not have enough confirmations."
    assert result.amount_paid_sats is None
    assert result.confirmations == 1


def test_verify_allows_zero_confirmations_when_threshold_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tx_constants, "MIN_CONFIRMATIONS", 0)
    verifier = DummyBaseVerifier(tx=make_tx(confirmations=0))

    result = verifier.verify(make_request())

    assert result.success is True
    assert result.reason is None
    assert result.amount_paid_sats == 50
    assert result.confirmations == 0


def test_verify_rejects_transaction_with_insufficient_treasury_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tx_constants, "MIN_CONFIRMATIONS", 0)
    verifier = DummyBaseVerifier(
        tx=make_tx(
            outputs=[
                NormalizedTxOutput(
                    value_sats=20,
                    address="bc1qtarget",
                    script_hex="0014aaaa",
                ),
                NormalizedTxOutput(
                    value_sats=0,
                    address=None,
                    script_hex="6a04deadbeef",
                ),
            ]
        )
    )

    result = verifier.verify(make_request(fee_sats=50))

    assert result.success is False
    assert result.reason == "Transaction paid too little to the treasury address."
    assert result.amount_paid_sats == 20
    assert result.confirmations == 1


def test_verify_rejects_transaction_without_expected_commitment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tx_constants, "MIN_CONFIRMATIONS", 0)
    verifier = DummyBaseVerifier(
        tx=make_tx(
            outputs=[
                NormalizedTxOutput(
                    value_sats=50,
                    address="bc1qtarget",
                    script_hex="0014aaaa",
                ),
                NormalizedTxOutput(
                    value_sats=0,
                    address=None,
                    script_hex="6a04cafebabe",
                ),
            ]
        )
    )

    result = verifier.verify(make_request(registration_commitment="deadbeef"))

    assert result.success is False
    assert (
        result.reason
        == "Transaction does not contain the expected registration commitment."
    )
    assert result.amount_paid_sats == 50
    assert result.confirmations == 1


def test_verify_succeeds_when_transaction_meets_all_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tx_constants, "MIN_CONFIRMATIONS", 0)
    verifier = DummyBaseVerifier(tx=make_tx())

    result = verifier.verify(make_request())

    assert result.success is True
    assert result.reason is None
    assert result.amount_paid_sats == 50
    assert result.confirmations == 1


# =========================================================
# _sum_outputs_for_address()
# =========================================================
def test_sum_outputs_for_address_adds_multiple_matching_outputs() -> None:
    tx = NormalizedTransaction(
        txid="txid",
        confirmations=1,
        outputs=[
            NormalizedTxOutput(
                value_sats=10,
                address="bc1qtarget",
                script_hex="0014aaaa",
            ),
            NormalizedTxOutput(
                value_sats=25,
                address="bc1qtarget",
                script_hex="0014bbbb",
            ),
            NormalizedTxOutput(
                value_sats=99,
                address="bc1qother",
                script_hex="0014cccc",
            ),
        ],
    )

    assert BaseVerifier._sum_outputs_for_address(tx, "bc1qtarget") == 35


def test_sum_outputs_for_address_ignores_outputs_without_matching_address() -> None:
    tx = NormalizedTransaction(
        txid="txid",
        confirmations=1,
        outputs=[
            NormalizedTxOutput(
                value_sats=10,
                address=None,
                script_hex="0014aaaa",
            ),
            NormalizedTxOutput(
                value_sats=25,
                address="bc1qother",
                script_hex="0014bbbb",
            ),
        ],
    )

    assert BaseVerifier._sum_outputs_for_address(tx, "bc1qtarget") == 0


# =========================================================
# _contains_registration_commitment()
# =========================================================
def test_contains_registration_commitment_matches_op_return_by_script_hex() -> None:
    tx = NormalizedTransaction(
        txid="txid",
        confirmations=1,
        outputs=[
            NormalizedTxOutput(
                value_sats=10,
                address="bc1qexample",
                script_hex="0014abcd",
            ),
            NormalizedTxOutput(
                value_sats=0,
                address=None,
                script_hex="6a04deadbeef",
            ),
        ],
    )

    assert BaseVerifier._contains_registration_commitment(tx, "deadbeef") is True


def test_contains_registration_commitment_rejects_invalid_expected_hex() -> None:
    tx = NormalizedTransaction(
        txid="txid",
        confirmations=1,
        outputs=[
            NormalizedTxOutput(
                value_sats=0,
                address=None,
                script_hex="6a04deadbeef",
            ),
        ],
    )

    assert BaseVerifier._contains_registration_commitment(tx, "zz") is False


# =========================================================
# _extract_op_return_payload_hex()
# =========================================================
@pytest.mark.parametrize(
    ("script_hex", "expected_payload"),
    [
        ("6a00", ""),
        ("6a04deadbeef", "deadbeef"),
        ("6a4c04deadbeef", "deadbeef"),
        ("6a4d0400deadbeef", "deadbeef"),
        ("6a4e04000000deadbeef", "deadbeef"),
    ],
)
def test_extract_op_return_payload_hex_parses_supported_push_encodings(
    script_hex: str,
    expected_payload: str,
) -> None:
    assert BaseVerifier._extract_op_return_payload_hex(script_hex) == expected_payload


@pytest.mark.parametrize(
    "script_hex",
    [
        "",
        "00",
        "6a",
        "6a0",
        "6azz",
        "6a02zzzz",
        "6a02aa",
        "6a4c",
        "6a4czzdeadbeef",
        "6a4c04deadbe",
        "6a4d",
        "6a4dzzzzdeadbeef",
        "6a4d0400deadbe",
        "6a4e",
        "6a4ezzzzzzzzdeadbeef",
        "6a4e04000000deadbe",
        "6a51deadbeef",
    ],
)
def test_extract_op_return_payload_hex_rejects_invalid_scripts(script_hex: str) -> None:
    assert BaseVerifier._extract_op_return_payload_hex(script_hex) is None

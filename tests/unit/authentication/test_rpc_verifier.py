from __future__ import annotations

from typing import Any

import pytest

from authentication.bitcoin.rpc_errors import BitcoinRpcErrorCode
from authentication.bitcoin.rpc_client import BitcoinRpcError
from authentication.transaction_verification.exceptions import TransactionFetchError
from authentication.transaction_verification.models import NormalizedTxOutput
from authentication.transaction_verification.rpc_verifier import RpcVerifier


class DummyRpcClient:
    def __init__(
        self,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error

    def get_raw_transaction(self, txid: str, verbosity: int = 1) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise AssertionError("DummyRpcClient requires a result or error.")
        return self._result


def make_verifier() -> RpcVerifier:
    return RpcVerifier(rpc_client=None)  # type: ignore[arg-type]


def make_rpc_tx(
    *,
    txid: str = "ab" * 32,
    confirmations: int = 1,
    vout: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "txid": txid,
        "confirmations": confirmations,
        "vout": (
            vout
            if vout is not None
            else [
                {
                    "value": 0.5,
                    "scriptPubKey": {
                        "address": " bc1qtarget ",
                        "hex": "0014aaaa",
                    },
                },
                {
                    "value": 0,
                    "scriptPubKey": {
                        "hex": "6a04deadbeef",
                    },
                },
            ]
        ),
    }


# =========================================================
# _fetch_transaction()
# =========================================================
def test_fetch_transaction_returns_normalized_transaction_for_valid_rpc_response() -> (
    None
):
    verifier = RpcVerifier(rpc_client=DummyRpcClient(result=make_rpc_tx()))  # type: ignore[arg-type]

    result = verifier._fetch_transaction("ab" * 32)

    assert result is not None
    assert result.txid == "ab" * 32
    assert result.confirmations == 1
    assert result.outputs == [
        NormalizedTxOutput(
            value_sats=50_000_000,
            address="bc1qtarget",
            script_hex="0014aaaa",
        ),
        NormalizedTxOutput(
            value_sats=0,
            address=None,
            script_hex="6a04deadbeef",
        ),
    ]


def test_fetch_transaction_returns_none_for_missing_transaction() -> None:
    verifier = RpcVerifier(
        rpc_client=DummyRpcClient(
            error=BitcoinRpcError(
                method="getrawtransaction",
                code=BitcoinRpcErrorCode.RPC_INVALID_ADDRESS_OR_KEY,
                rpc_message="No such mempool or blockchain transaction.",
            )
        )
    )  # type: ignore[arg-type]

    result = verifier._fetch_transaction("ab" * 32)

    assert result is None


def test_fetch_transaction_wraps_non_not_found_rpc_errors() -> None:
    verifier = RpcVerifier(
        rpc_client=DummyRpcClient(
            error=BitcoinRpcError(
                method="getrawtransaction",
                code=BitcoinRpcErrorCode.RPC_MISC_ERROR,
                rpc_message="Backend unavailable.",
            )
        )
    )  # type: ignore[arg-type]

    with pytest.raises(
        TransactionFetchError, match="Failed to fetch transaction data:"
    ):
        verifier._fetch_transaction("ab" * 32)


def test_fetch_transaction_wraps_normalization_failures() -> None:
    verifier = RpcVerifier(
        rpc_client=DummyRpcClient(result={"txid": "", "confirmations": 1, "vout": []})
    )  # type: ignore[arg-type]

    with pytest.raises(
        TransactionFetchError,
        match="Failed to normalize transaction data: Invalid txid in RPC response.",
    ):
        verifier._fetch_transaction("ab" * 32)


# =========================================================
# _normalize_transaction()
# =========================================================
def test_normalize_transaction_returns_normalized_outputs() -> None:
    verifier = make_verifier()

    result = verifier._normalize_transaction(make_rpc_tx())

    assert result.txid == "ab" * 32
    assert result.confirmations == 1
    assert result.outputs == [
        NormalizedTxOutput(
            value_sats=50_000_000,
            address="bc1qtarget",
            script_hex="0014aaaa",
        ),
        NormalizedTxOutput(
            value_sats=0,
            address=None,
            script_hex="6a04deadbeef",
        ),
    ]


@pytest.mark.parametrize(
    ("tx", "expected_message"),
    [
        ({"txid": "", "confirmations": 1, "vout": []}, "Invalid txid in RPC response."),
        (
            {"txid": 123, "confirmations": 1, "vout": []},
            "Invalid txid in RPC response.",
        ),
        (
            {"txid": "ab" * 32, "confirmations": True, "vout": []},
            "Invalid confirmations in RPC response.",
        ),
        (
            {"txid": "ab" * 32, "confirmations": "1", "vout": []},
            "Invalid confirmations in RPC response.",
        ),
        (
            {"txid": "ab" * 32, "confirmations": 1, "vout": {}},
            "Invalid vout in RPC response.",
        ),
        (
            {"txid": "ab" * 32, "confirmations": 1, "vout": [123]},
            "Invalid vout entry in RPC response.",
        ),
        (
            {
                "txid": "ab" * 32,
                "confirmations": 1,
                "vout": [{"value": "bad", "scriptPubKey": {"hex": "0014aaaa"}}],
            },
            "Invalid BTC amount in RPC response.",
        ),
        (
            {
                "txid": "ab" * 32,
                "confirmations": 1,
                "vout": [{"value": 1, "scriptPubKey": None}],
            },
            "Invalid scriptPubKey in RPC response.",
        ),
        (
            {
                "txid": "ab" * 32,
                "confirmations": 1,
                "vout": [{"value": 1, "scriptPubKey": {"hex": ""}}],
            },
            "Invalid scriptPubKey hex in RPC response.",
        ),
        (
            {
                "txid": "ab" * 32,
                "confirmations": 1,
                "vout": [
                    {"value": 1, "scriptPubKey": {"address": 123, "hex": "0014aaaa"}}
                ],
            },
            "Invalid address in scriptPubKey.",
        ),
    ],
)
def test_normalize_transaction_rejects_malformed_fields(
    tx: dict[str, Any],
    expected_message: str,
) -> None:
    verifier = make_verifier()

    with pytest.raises(ValueError, match=expected_message):
        verifier._normalize_transaction(tx)


# =========================================================
# _extract_address()
# =========================================================
def test_extract_address_prefers_stripped_address_field() -> None:
    assert RpcVerifier._extract_address({"address": " bc1qtarget "}) == "bc1qtarget"


def test_extract_address_falls_back_to_first_non_empty_addresses_entry() -> None:
    assert (
        RpcVerifier._extract_address(
            {"addresses": ["   ", " bc1qtarget ", "bc1qother"]}
        )
        == "bc1qtarget"
    )


@pytest.mark.parametrize(
    "script_pub_key",
    [
        {},
        {"address": "   "},
        {"addresses": ["   ", ""]},
    ],
)
def test_extract_address_returns_none_when_no_usable_address_is_present(
    script_pub_key: dict[str, Any],
) -> None:
    assert RpcVerifier._extract_address(script_pub_key) is None


@pytest.mark.parametrize(
    "script_pub_key",
    [
        {"address": 123},
        {"addresses": "not-a-list"},
        {"addresses": ["bc1qtarget", 123]},
    ],
)
def test_extract_address_rejects_malformed_address_fields(
    script_pub_key: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        RpcVerifier._extract_address(script_pub_key)


# =========================================================
# _btc_to_sats()
# =========================================================
@pytest.mark.parametrize(
    ("value_btc", "expected_sats"),
    [
        (1, 100_000_000),
        (0.1, 10_000_000),
        (0.00000001, 1),
        ("0.5", 50_000_000),
    ],
)
def test_btc_to_sats_converts_exact_btc_amounts(
    value_btc: int | float | str, expected_sats: int
) -> None:
    assert RpcVerifier._btc_to_sats(value_btc) == expected_sats


@pytest.mark.parametrize(
    "value_btc",
    [
        True,
        object(),
        "not-a-number",
        "0.000000001",
    ],
)
def test_btc_to_sats_rejects_invalid_amounts(value_btc: object) -> None:
    with pytest.raises(ValueError):
        RpcVerifier._btc_to_sats(value_btc)

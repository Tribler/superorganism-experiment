from __future__ import annotations

import httpx
import pytest

from authentication.bitcoin.rpc_client import BitcoinRpcClient, BitcoinRpcConfig
from authentication.bitcoin.rpc_errors import BitcoinRpcError


# =========================================================
# from_config()
# =========================================================
def test_from_config_url_encodes_wallet_name() -> None:
    client = BitcoinRpcClient.from_config(
        BitcoinRpcConfig(
            rpc_url="http://localhost:18443/",
            rpc_user="user",
            rpc_password="pass",
            wallet_name="wallet with/slash",
        )
    )

    try:
        assert (
            client._rpc_endpoint
            == "http://localhost:18443/wallet/wallet%20with%2Fslash"
        )
    finally:
        client.close()


def test_from_config_ignores_blank_wallet_name() -> None:
    client = BitcoinRpcClient.from_config(
        BitcoinRpcConfig(
            rpc_url="  http://localhost:18443/  ",
            rpc_user="user",
            rpc_password="pass",
            wallet_name="   ",
        )
    )

    try:
        assert client._rpc_endpoint == "http://localhost:18443"
    finally:
        client.close()


def test_from_config_rejects_blank_rpc_url() -> None:
    with pytest.raises(ValueError, match="rpc_url must not be empty"):
        BitcoinRpcClient.from_config(
            BitcoinRpcConfig(
                rpc_url="   ",
                rpc_user="user",
                rpc_password="pass",
            )
        )


@pytest.mark.parametrize("timeout_seconds", [0, -1.0])
def test_from_config_rejects_non_positive_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        BitcoinRpcClient.from_config(
            BitcoinRpcConfig(
                rpc_url="http://localhost:18443",
                rpc_user="user",
                rpc_password="pass",
                timeout_seconds=timeout_seconds,
            )
        )


# =========================================================
# __exit__()
# =========================================================
def test_context_manager_closes_underlying_client() -> None:
    http_client = httpx.Client()

    with BitcoinRpcClient(http_client, "http://localhost:18443") as rpc_client:
        assert rpc_client is not None
        assert http_client.is_closed is False

    assert http_client.is_closed is True


# =========================================================
# close()
# =========================================================
def test_close_closes_underlying_client() -> None:
    http_client = httpx.Client()
    client = BitcoinRpcClient(http_client, "http://localhost:18443")

    client.close()

    assert http_client.is_closed is True


# =========================================================
# call()
# =========================================================
def test_call_rejects_non_string_method() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="method must be a string"):
            client.call(123)  # type: ignore[arg-type]
    finally:
        client.close()


@pytest.mark.parametrize("method", ["", "   "])
def test_call_rejects_blank_method(method: str) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="method must not be empty"):
            client.call(method)
    finally:
        client.close()


def test_call_returns_result_for_valid_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"txid": "ab" * 32},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        result = client.call("getrawtransaction", "ab" * 32, 1)
    finally:
        client.close()

    assert result == {"txid": "ab" * 32}


def test_call_wraps_transport_errors() -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("connection refused", request=request)
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError, match="RPC request failed:"):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


def test_call_wraps_http_status_errors() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, request=request, text="service unavailable")
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError) as exc_info:
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()

    assert exc_info.value.rpc_message == (
        "RPC HTTP error 503 Service Unavailable. Response body: service unavailable"
    )


def test_call_wraps_invalid_json_response() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    response = httpx.Response(200, request=request, text="not-json")
    client = BitcoinRpcClient(
        httpx.Client(transport=httpx.MockTransport(lambda req: response)),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError, match="RPC response was not valid JSON"):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


def test_call_rejects_non_object_json_payload() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, request=request, json=["not", "an", "object"]
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError, match="RPC response is not a JSON object"):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


def test_call_prefers_json_rpc_error_payload_over_http_status() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            500,
            request=request,
            json={
                "result": None,
                "error": {"code": -5, "message": "No such mempool tx"},
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError) as exc_info:
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()

    assert exc_info.value.code == -5
    assert exc_info.value.rpc_message == "No such mempool tx"


def test_call_rejects_missing_result_field() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            BitcoinRpcError,
            match="RPC response did not contain a result field",
        ):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


def test_call_rejects_mismatched_response_id() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 999, "result": {}, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            BitcoinRpcError,
            match="RPC response id did not match request id",
        ):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


def test_call_wraps_non_dict_error_payload() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": None, "error": "boom"},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(BitcoinRpcError, match="Unknown RPC error: boom"):
            client.call("getrawtransaction", "00" * 32, 1)
    finally:
        client.close()


# =========================================================
# _raise_for_status()
# =========================================================
def test_raise_for_status_does_not_raise_for_success_response() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    response = httpx.Response(200, request=request)

    BitcoinRpcClient._raise_for_status("getrawtransaction", response)


def test_raise_for_status_includes_status_and_reason_phrase() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    response = httpx.Response(503, request=request, text="")

    with pytest.raises(BitcoinRpcError) as exc_info:
        BitcoinRpcClient._raise_for_status("getrawtransaction", response)

    assert exc_info.value.rpc_message == "RPC HTTP error 503 Service Unavailable."


def test_raise_for_status_includes_response_body_when_present() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    response = httpx.Response(503, request=request, text="service unavailable")

    with pytest.raises(BitcoinRpcError) as exc_info:
        BitcoinRpcClient._raise_for_status("getrawtransaction", response)

    assert exc_info.value.rpc_message == (
        "RPC HTTP error 503 Service Unavailable. Response body: service unavailable"
    )


def test_raise_for_status_omits_response_body_when_empty() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    response = httpx.Response(401, request=request, text="   ")

    with pytest.raises(BitcoinRpcError) as exc_info:
        BitcoinRpcClient._raise_for_status("getrawtransaction", response)

    assert exc_info.value.rpc_message == "RPC HTTP error 401 Unauthorized."


def test_raise_for_status_truncates_long_response_body() -> None:
    request = httpx.Request("POST", "http://localhost:18443")
    body = "x" * 250
    response = httpx.Response(500, request=request, text=body)

    with pytest.raises(BitcoinRpcError) as exc_info:
        BitcoinRpcClient._raise_for_status("getrawtransaction", response)

    assert exc_info.value.rpc_message == (
        f"RPC HTTP error 500 Internal Server Error. Response body: {'x' * 200}"
    )


# =========================================================
# get_raw_transaction()
# =========================================================
def test_get_raw_transaction_rejects_empty_txid() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="txid must not be empty"):
            client.get_raw_transaction("")
    finally:
        client.close()


@pytest.mark.parametrize("txid", ["ab", "zz" * 32])
def test_get_raw_transaction_rejects_invalid_txid_format(txid: str) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(
            ValueError,
            match="txid must be a 64-character hexadecimal string",
        ):
            client.get_raw_transaction(txid, verbosity=1)
    finally:
        client.close()


@pytest.mark.parametrize("verbosity", [0, -1, 3])
def test_get_raw_transaction_rejects_unsupported_verbosity(verbosity: int) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="verbosity must be 1 or 2"):
            client.get_raw_transaction("ab" * 32, verbosity=verbosity)
    finally:
        client.close()


# =========================================================
# sats_to_btc_string()
# =========================================================
def test_sats_to_btc_string_returns_expected_btc_string_for_valid_amount() -> None:
    assert BitcoinRpcClient.sats_to_btc_string(12_345_678) == "0.12345678"


def test_sats_to_btc_string_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="amount_sats must be non-negative"):
        BitcoinRpcClient.sats_to_btc_string(-1)

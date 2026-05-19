from __future__ import annotations

import httpx
import pytest

from bitcoin.rpc_client import BitcoinRpcClient, BitcoinRpcConfig
from bitcoin.rpc_errors import BitcoinRpcError


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
# get_block_count()
# =========================================================
def test_get_block_count_rejects_boolean_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": True, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(ValueError, match="getblockcount returned a non-int result"):
            client.get_block_count()
    finally:
        client.close()


def test_get_block_count_rejects_non_integer_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": "123", "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(ValueError, match="getblockcount returned a non-int result"):
            client.get_block_count()
    finally:
        client.close()


def test_get_block_count_rejects_negative_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": -1, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="getblockcount returned a negative block height",
        ):
            client.get_block_count()
    finally:
        client.close()


# =========================================================
# get_tx_out()
# =========================================================
def test_get_tx_out_returns_none_for_spent_or_unknown_output() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": None, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        result = client.get_tx_out("ab" * 32, 0)
    finally:
        client.close()

    assert result is None


def test_get_tx_out_rejects_invalid_txid() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(
            ValueError,
            match="txid must be a 64-character hexadecimal string",
        ):
            client.get_tx_out("invalid", 0)
    finally:
        client.close()


@pytest.mark.parametrize("vout", [True, "0"])
def test_get_tx_out_rejects_non_integer_vout(vout: object) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="vout must be an integer"):
            client.get_tx_out("ab" * 32, vout)  # type: ignore[arg-type]
    finally:
        client.close()


def test_get_tx_out_rejects_negative_vout() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="vout must be non-negative"):
            client.get_tx_out("ab" * 32, -1)
    finally:
        client.close()


def test_get_tx_out_rejects_non_boolean_include_mempool() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="include_mempool must be a bool"):
            client.get_tx_out("ab" * 32, 0, include_mempool="false")  # type: ignore[arg-type]
    finally:
        client.close()


def test_get_tx_out_rejects_non_dict_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": ["not", "a", "dict"],
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(ValueError, match="gettxout returned a non-dict result"):
            client.get_tx_out("ab" * 32, 0)
    finally:
        client.close()


# =========================================================
# create_raw_transaction()
# =========================================================
def test_create_raw_transaction_rejects_non_list_inputs() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="inputs must be a list"):
            client.create_raw_transaction(
                inputs={"txid": "ab" * 32, "vout": 0},  # type: ignore[arg-type]
                outputs=[],
            )
    finally:
        client.close()


def test_create_raw_transaction_rejects_non_list_outputs() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="outputs must be a list"):
            client.create_raw_transaction(
                inputs=[],
                outputs={"bcrt1qdest": 0.1},  # type: ignore[arg-type]
            )
    finally:
        client.close()


@pytest.mark.parametrize("locktime", [True, "0"])
def test_create_raw_transaction_rejects_non_integer_locktime(
    locktime: object,
) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="locktime must be an integer"):
            client.create_raw_transaction(
                inputs=[],
                outputs=[],
                locktime=locktime,  # type: ignore[arg-type]
            )
    finally:
        client.close()


def test_create_raw_transaction_rejects_negative_locktime() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="locktime must be non-negative"):
            client.create_raw_transaction(
                inputs=[],
                outputs=[],
                locktime=-1,
            )
    finally:
        client.close()


def test_create_raw_transaction_rejects_non_boolean_replaceable() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="replaceable must be a bool"):
            client.create_raw_transaction(
                inputs=[],
                outputs=[],
                replaceable="false",  # type: ignore[arg-type]
            )
    finally:
        client.close()


def test_create_raw_transaction_rejects_non_string_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"hex": "deadbeef"},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="createrawtransaction returned a non-string result",
        ):
            client.create_raw_transaction(inputs=[], outputs=[])
    finally:
        client.close()


# =========================================================
# create_psbt()
# =========================================================
def test_create_psbt_rejects_non_list_inputs() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="inputs must be a list"):
            client.create_psbt(
                inputs={"txid": "ab" * 32, "vout": 0},  # type: ignore[arg-type]
                outputs=[],
            )
    finally:
        client.close()


def test_create_psbt_rejects_non_list_outputs() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="outputs must be a list"):
            client.create_psbt(
                inputs=[],
                outputs={"bcrt1qdest": 0.1},  # type: ignore[arg-type]
            )
    finally:
        client.close()


@pytest.mark.parametrize("locktime", [True, "0"])
def test_create_psbt_rejects_non_integer_locktime(locktime: object) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="locktime must be an integer"):
            client.create_psbt(
                inputs=[],
                outputs=[],
                locktime=locktime,  # type: ignore[arg-type]
            )
    finally:
        client.close()


def test_create_psbt_rejects_negative_locktime() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="locktime must be non-negative"):
            client.create_psbt(
                inputs=[],
                outputs=[],
                locktime=-1,
            )
    finally:
        client.close()


def test_create_psbt_rejects_non_boolean_replaceable() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="replaceable must be a bool"):
            client.create_psbt(
                inputs=[],
                outputs=[],
                replaceable="false",  # type: ignore[arg-type]
            )
    finally:
        client.close()


def test_create_psbt_rejects_non_string_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"psbt": "cHNidP8BAAoCAAAAAQ=="},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="createpsbt returned a non-string result",
        ):
            client.create_psbt(inputs=[], outputs=[])
    finally:
        client.close()


@pytest.mark.parametrize("psbt", ["", "   "])
def test_create_psbt_rejects_empty_string_result(psbt: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": psbt,
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="createpsbt returned an empty PSBT string",
        ):
            client.create_psbt(inputs=[], outputs=[])
    finally:
        client.close()


def test_create_psbt_rejects_non_base64_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": "not-base64!",
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="createpsbt returned a non-base64 PSBT string",
        ):
            client.create_psbt(inputs=[], outputs=[])
    finally:
        client.close()


def test_create_psbt_returns_trimmed_base64_psbt() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": "  cHNidP8BAAoCAAAAAQ==  ",
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        result = client.create_psbt(inputs=[], outputs=[])
    finally:
        client.close()

    assert result == "cHNidP8BAAoCAAAAAQ=="


# =========================================================
# finalize_psbt()
# =========================================================
@pytest.mark.parametrize("psbt_base64", [123, None, "", "   ", "not-base64!"])
def test_finalize_psbt_rejects_invalid_psbt_base64(psbt_base64: object) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="psbt_base64 must"):
            client.finalize_psbt(psbt_base64)  # type: ignore[arg-type]
    finally:
        client.close()


def test_finalize_psbt_rejects_non_boolean_extract() -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="extract must be a bool"):
            client.finalize_psbt("cHNidP8BAAoCAAAAAQ==", extract="true")  # type: ignore[arg-type]
    finally:
        client.close()


def test_finalize_psbt_rejects_non_dict_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": "nope", "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(ValueError, match="finalizepsbt returned a non-dict result"):
            client.finalize_psbt("cHNidP8BAAoCAAAAAQ==")
    finally:
        client.close()


# =========================================================
# finalize_psbt_extract_tx_hex()
# =========================================================
def test_finalize_psbt_extract_tx_hex_rejects_non_bool_complete_flag() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"complete": "yes", "hex": "deadbeef"},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="finalizepsbt returned a non-bool complete flag",
        ):
            client.finalize_psbt_extract_tx_hex("cHNidP8BAAoCAAAAAQ==")
    finally:
        client.close()


def test_finalize_psbt_extract_tx_hex_rejects_incomplete_psbt() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"complete": False},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="finalizepsbt returned an incomplete PSBT",
        ):
            client.finalize_psbt_extract_tx_hex("cHNidP8BAAoCAAAAAQ==")
    finally:
        client.close()


def test_finalize_psbt_extract_tx_hex_rejects_non_string_hex_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"complete": True, "hex": 123},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="finalizepsbt returned a non-string hex result",
        ):
            client.finalize_psbt_extract_tx_hex("cHNidP8BAAoCAAAAAQ==")
    finally:
        client.close()


def test_finalize_psbt_extract_tx_hex_returns_trimmed_hex() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"complete": True, "hex": "  deadbeef  "},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        result = client.finalize_psbt_extract_tx_hex("cHNidP8BAAoCAAAAAQ==")
    finally:
        client.close()

    assert result == "deadbeef"


# =========================================================
# decode_raw_transaction()
# =========================================================
@pytest.mark.parametrize("raw_tx_hex", [123, None, "", "   ", "zz"])
def test_decode_raw_transaction_rejects_invalid_raw_tx_hex(
    raw_tx_hex: object,
) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="raw_tx_hex must"):
            client.decode_raw_transaction(raw_tx_hex)  # type: ignore[arg-type]
    finally:
        client.close()


def test_decode_raw_transaction_rejects_non_dict_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": "deadbeef", "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="decoderawtransaction returned a non-dict result",
        ):
            client.decode_raw_transaction("deadbeef")
    finally:
        client.close()


# =========================================================
# send_raw_transaction()
# =========================================================
@pytest.mark.parametrize("raw_tx_hex", [123, None, "", "   ", "zz"])
def test_send_raw_transaction_rejects_invalid_raw_tx_hex(
    raw_tx_hex: object,
) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="raw_tx_hex must"):
            client.send_raw_transaction(raw_tx_hex)  # type: ignore[arg-type]
    finally:
        client.close()


def test_send_raw_transaction_rejects_non_string_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"hex": "deadbeef"},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="sendrawtransaction returned a non-string result",
        ):
            client.send_raw_transaction("deadbeef")
    finally:
        client.close()


# =========================================================
# test_mempool_accept()
# =========================================================
@pytest.mark.parametrize("raw_tx_hex", [123, None, "", "   ", "zz"])
def test_test_mempool_accept_rejects_invalid_raw_tx_hex(
    raw_tx_hex: object,
) -> None:
    client = BitcoinRpcClient(httpx.Client(), "http://localhost:18443")

    try:
        with pytest.raises(ValueError, match="raw_tx_hex must"):
            client.test_mempool_accept(raw_tx_hex)  # type: ignore[arg-type]
    finally:
        client.close()


def test_test_mempool_accept_rejects_non_list_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "1.0",
                "id": 1,
                "result": {"allowed": True},
                "error": None,
            },
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="testmempoolaccept returned an unexpected result",
        ):
            client.test_mempool_accept("deadbeef")
    finally:
        client.close()


@pytest.mark.parametrize("result", [[], [{"allowed": True}, {"allowed": False}]])
def test_test_mempool_accept_rejects_wrong_result_length(result: object) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": result, "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="testmempoolaccept returned an unexpected result",
        ):
            client.test_mempool_accept("deadbeef")
    finally:
        client.close()


def test_test_mempool_accept_rejects_non_dict_result_item() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "1.0", "id": 1, "result": ["not-a-dict"], "error": None},
        )
    )
    client = BitcoinRpcClient(
        httpx.Client(transport=transport),
        "http://localhost:18443",
    )

    try:
        with pytest.raises(
            ValueError,
            match="testmempoolaccept result item was not a dict",
        ):
            client.test_mempool_accept("deadbeef")
    finally:
        client.close()

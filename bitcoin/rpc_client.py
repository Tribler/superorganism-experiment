from __future__ import annotations

import base64
import binascii

from dataclasses import dataclass
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from bitcoin.rpc_errors import BitcoinRpcError
from bitcoin.utils import validate_psbt_base64, validate_raw_tx_hex, validate_txid


@dataclass(frozen=True)
class BitcoinRpcConfig:
    rpc_url: str
    rpc_user: str
    rpc_password: str
    wallet_name: str | None = None
    timeout_seconds: float = 5.0


class BitcoinRpcClient:
    def __init__(self, client: httpx.Client, rpc_endpoint: str) -> None:
        self._client = client
        self._rpc_endpoint = rpc_endpoint
        self._request_id = 0

    @classmethod
    def from_config(cls, config: BitcoinRpcConfig) -> "BitcoinRpcClient":
        """
        Construct a BitcoinRpcClient from a validated RPC configuration.

        The RPC base URL is normalized by trimming surrounding whitespace and removing any
        trailing slash. If a non-empty wallet name is provided, the client is configured
        to use the wallet-specific RPC endpoint.

        :param config: The RPC configuration to build the client from.
        :returns: A configured Bitcoin RPC client instance.
        :raises ValueError: If rpc_url is empty or timeout_seconds is not positive.
        """
        rpc_url = config.rpc_url.strip().rstrip("/")
        if not rpc_url:
            raise ValueError("rpc_url must not be empty.")

        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        wallet_name = (
            config.wallet_name.strip() if config.wallet_name is not None else None
        )
        rpc_endpoint = (
            f"{rpc_url}/wallet/{quote(wallet_name, safe='')}"
            if wallet_name
            else rpc_url
        )

        client = httpx.Client(
            timeout=config.timeout_seconds,
            auth=(config.rpc_user, config.rpc_password),
            headers={"content-type": "application/json"},
        )
        return cls(client=client, rpc_endpoint=rpc_endpoint)

    def __enter__(self) -> "BitcoinRpcClient":
        """Return this client for use in a context manager."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client when leaving the context."""
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def call(self, method: str, *params: Any) -> Any:
        """
        Invoke a Bitcoin Core JSON-RPC method and return its result field.

        This method validates the RPC method name, sends the JSON-RPC request, checks for
        transport- and RPC-level errors, validates the response shape, and ensures that
        the response ID matches the issued request.

        :param method: The JSON-RPC method name to call. Must be a non-empty string.
        :param params: Positional parameters to pass to the RPC method.
        :returns: The value of the result field from the JSON-RPC response.
        :raises ValueError: If method is not a string or is empty after stripping.
        :raises BitcoinRpcError: If the HTTP request fails, the response status indicates
                                 an error, the response is malformed, the RPC reports an
                                 error, or the response ID does not match the request ID.
        """
        if not isinstance(method, str):
            raise ValueError("method must be a string.")

        method = method.strip()
        if not method:
            raise ValueError("method must not be empty.")

        self._request_id += 1
        request_id = self._request_id

        try:
            response = self._client.post(
                self._rpc_endpoint,
                json={
                    "jsonrpc": "1.0",
                    "id": request_id,
                    "method": method,
                    "params": list(params),
                },
            )
        except httpx.RequestError as exc:
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message=f"RPC request failed: {exc}",
            ) from exc

        try:
            payload = response.json()
        except ValueError:
            self._raise_for_status(method, response)
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message="RPC response was not valid JSON.",
            )

        if not isinstance(payload, dict):
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message="RPC response is not a JSON object.",
            )

        error = payload.get("error")
        if error is not None:
            if isinstance(error, dict):
                raise BitcoinRpcError(
                    method=method,
                    code=error.get("code"),
                    rpc_message=str(error.get("message", "Unknown RPC error.")),
                )

            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message=f"Unknown RPC error: {error}",
            )

        self._raise_for_status(method, response)

        if "result" not in payload:
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message="RPC response did not contain a result field.",
            )

        if payload.get("id") != request_id:
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message="RPC response id did not match request id.",
            )

        return payload.get("result")

    @staticmethod
    def _raise_for_status(method: str, response: httpx.Response) -> None:
        """
        Raise a BitcoinRpcError if the HTTP response status indicates failure.

        This helper wraps httpx.Response.raise_for_status and converts any resulting
        httpx.HTTPStatusError into a domain-specific BitcoinRpcError. The resulting error
        message includes the RPC method name, the HTTP status code, the reason phrase when
        available, and a truncated prefix of the response body to aid debugging.

        :param method: The name of the RPC method associated with the HTTP request.
        :param response: The HTTP response returned by the RPC endpoint.
        :returns: None if the response status is successful.
        :raises BitcoinRpcError: If the HTTP response status code indicates an error.
        """
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            reason = response.reason_phrase or "Unknown"
            body = response.text.strip()
            body_suffix = f" Response body: {body[:200]}" if body else ""
            raise BitcoinRpcError(
                method=method,
                code=None,
                rpc_message=(
                    f"RPC HTTP error {response.status_code} {reason}.{body_suffix}"
                ),
            ) from exc

    def get_raw_transaction(self, txid: str, verbosity: int = 1) -> dict[str, Any]:
        """
        Retrieve a decoded raw transaction from the Bitcoin RPC interface.

        This method wraps the getrawtransaction RPC call and returns the decoded
        transaction object for the given transaction ID.

        note: Although Bitcoin Core supports verbosity levels 0, 1, and 2 for
        getrawtransaction, this wrapper intentionally accepts only verbosity levels 1 and
        2. This is because verbosity 0 returns a raw transaction hex string, whereas this
        method guarantees a dict[str, Any] return value and validates the RPC result
        accordingly. Restricting the accepted verbosity values avoids a mismatch between
        the Bitcoin Core RPC behavior and this method's typed return contract.

        :param txid: The transaction ID of the transaction to retrieve.
        :param verbosity: The Bitcoin Core verbosity level. Supported values are 1 and 2.
        :returns: The decoded transaction as returned by Bitcoin Core.
        :raises ValueError: If txid is not a valid 64-character hexadecimal string, if
                            verbosity is not 1 or 2, or if the RPC returns a
                            non-dictionary result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        txid = validate_txid(txid)

        if verbosity not in (1, 2):
            raise ValueError("verbosity must be 1 or 2.")

        result = self.call("getrawtransaction", txid, verbosity)
        if not isinstance(result, dict):
            raise ValueError("getrawtransaction returned a non-dict result.")
        return result

    def get_block_count(self) -> int:
        """
        Return the current blockchain height.

        Calls the getblockcount RPC method and validates that the response is a
        non-negative integer.

        :returns: The current chain height.
        :raises ValueError: If the RPC returns a non-integer or negative result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        result = self.call("getblockcount")

        if isinstance(result, bool) or not isinstance(result, int):
            raise ValueError("getblockcount returned a non-int result.")

        if result < 0:
            raise ValueError("getblockcount returned a negative block height.")

        return result

    def get_tx_out(
        self,
        txid: str,
        vout: int,
        include_mempool: bool = True,
    ) -> dict[str, Any] | None:
        """
        Return information about an unspent transaction output.

        Validates the transaction ID, output index, and mempool inclusion flag before
        calling the gettxout RPC method. Returns None when the requested output is not
        found or has already been spent.

        :param txid: Transaction ID containing the output.
        :param vout: Zero-based output index.
        :param include_mempool: Whether to consider the mempool when querying the UTXO.
        :returns: The decoded UTXO data, or None if the output is spent or unknown.
        :raises ValueError: If txid, vout, or include_mempool are invalid, or if the RPC
                            returns a non-dict non-None result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        txid = validate_txid(txid)

        if isinstance(vout, bool) or not isinstance(vout, int):
            raise ValueError("vout must be an integer.")
        if vout < 0:
            raise ValueError("vout must be non-negative.")

        if not isinstance(include_mempool, bool):
            raise ValueError("include_mempool must be a bool.")

        result = self.call("gettxout", txid, vout, include_mempool)

        if result is None:
            return None

        if not isinstance(result, dict):
            raise ValueError("gettxout returned a non-dict result.")

        return result

    def create_raw_transaction(
        self,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        locktime: int = 0,
        replaceable: bool = True,
    ) -> str:
        """
        Create a serialized raw transaction.

        Validates the transaction inputs, outputs, locktime, and replaceability flag
        before calling the createrawtransaction RPC method.

        :param inputs: Transaction inputs in Bitcoin Core RPC format.
        :param outputs: Transaction outputs in Bitcoin Core RPC format.
        :param locktime: Transaction locktime. Must be a non-negative integer.
        :param replaceable: Whether the transaction should signal BIP125 replaceability.
        :returns: The raw transaction hex string.
        :raises ValueError: If arguments are invalid or the RPC returns a non-string
                            result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        if not isinstance(inputs, list):
            raise ValueError("inputs must be a list.")
        if not isinstance(outputs, list):
            raise ValueError("outputs must be a list.")
        if isinstance(locktime, bool) or not isinstance(locktime, int):
            raise ValueError("locktime must be an integer.")
        if locktime < 0:
            raise ValueError("locktime must be non-negative.")
        if not isinstance(replaceable, bool):
            raise ValueError("replaceable must be a bool.")

        result = self.call(
            "createrawtransaction",
            inputs,
            outputs,
            locktime,
            replaceable,
        )
        if not isinstance(result, str):
            raise ValueError("createrawtransaction returned a non-string result.")
        return result

    def create_psbt(
        self,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        locktime: int = 0,
        replaceable: bool = True,
    ) -> str:
        """
        Create an unsigned PSBT.

        Validates the transaction inputs, outputs, locktime, and replaceability flag
        before calling the createpsbt RPC method.

        :param inputs: Transaction inputs in Bitcoin Core RPC format.
        :param outputs: Transaction outputs in Bitcoin Core RPC format.
        :param locktime: Transaction locktime. Must be a non-negative integer.
        :param replaceable: Whether the transaction should signal BIP125 replaceability.
        :returns: The PSBT as a base64-encoded string.
        :raises ValueError: If arguments are invalid or the RPC returns an invalid PSBT
                            string.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        if not isinstance(inputs, list):
            raise ValueError("inputs must be a list.")
        if not isinstance(outputs, list):
            raise ValueError("outputs must be a list.")
        if isinstance(locktime, bool) or not isinstance(locktime, int):
            raise ValueError("locktime must be an integer.")
        if locktime < 0:
            raise ValueError("locktime must be non-negative.")
        if not isinstance(replaceable, bool):
            raise ValueError("replaceable must be a bool.")

        result = self.call(
            "createpsbt",
            inputs,
            outputs,
            locktime,
            replaceable,
        )
        if not isinstance(result, str):
            raise ValueError("createpsbt returned a non-string result.")

        normalized = result.strip()
        if not normalized:
            raise ValueError("createpsbt returned an empty PSBT string.")

        try:
            base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("createpsbt returned a non-base64 PSBT string.") from exc

        return normalized

    def finalize_psbt(self, psbt_base64: str, extract: bool = True) -> dict[str, Any]:
        """
        Finalize a PSBT.

        Validates the PSBT base64 string and extract flag before calling the finalizepsbt
        RPC method.

        :param psbt_base64: The base64-encoded PSBT to finalize.
        :param extract: Whether to extract the fully signed transaction hex when complete.
        :returns: The finalizepsbt RPC result object.
        :raises ValueError: If arguments are invalid or the RPC returns a non-dict result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        psbt_base64 = validate_psbt_base64(psbt_base64)
        if not isinstance(extract, bool):
            raise ValueError("extract must be a bool.")

        result = self.call("finalizepsbt", psbt_base64, extract)
        if not isinstance(result, dict):
            raise ValueError("finalizepsbt returned a non-dict result.")
        return result

    def finalize_psbt_extract_tx_hex(self, psbt_base64: str) -> str:
        """
        Finalize a PSBT and return the extracted transaction hex.

        :param psbt_base64: The base64-encoded PSBT to finalize.
        :returns: The finalized raw transaction hex.
        :raises ValueError: If the PSBT is incomplete or the RPC result does not contain a
                            valid transaction hex.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        result = self.finalize_psbt(psbt_base64, extract=True)

        complete = result.get("complete")
        if not isinstance(complete, bool):
            raise ValueError("finalizepsbt returned a non-bool complete flag.")
        if not complete:
            raise ValueError("finalizepsbt returned an incomplete PSBT.")

        tx_hex = result.get("hex")
        if not isinstance(tx_hex, str):
            raise ValueError("finalizepsbt returned a non-string hex result.")

        return validate_raw_tx_hex(tx_hex)

    def decode_raw_transaction(self, raw_tx_hex: str) -> dict[str, Any]:
        """
        Decode a serialized raw transaction.

        Validates that the raw transaction is a non-empty hexadecimal string before
        calling the decoderawtransaction RPC method.

        :param raw_tx_hex: Raw transaction hex.
        :returns: The decoded transaction object.
        :raises ValueError: If raw_tx_hex is invalid or the RPC returns a non-dict result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        raw_tx_hex = validate_raw_tx_hex(raw_tx_hex)
        result = self.call("decoderawtransaction", raw_tx_hex)
        if not isinstance(result, dict):
            raise ValueError("decoderawtransaction returned a non-dict result.")
        return result

    def send_raw_transaction(self, raw_tx_hex: str) -> str:
        """
        Broadcast a serialized raw transaction.

        Validates the raw transaction hexadecimal string before calling the
        sendrawtransaction RPC method.

        :param raw_tx_hex: Raw transaction hex.
        :returns: The transaction ID of the broadcast transaction.
        :raises ValueError: If raw_tx_hex is invalid or the RPC returns a non-string
                            result.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        raw_tx_hex = validate_raw_tx_hex(raw_tx_hex)
        result = self.call("sendrawtransaction", raw_tx_hex)
        if not isinstance(result, str):
            raise ValueError("sendrawtransaction returned a non-string result.")
        return result

    def test_mempool_accept(self, raw_tx_hex: str) -> dict[str, Any]:
        """
        Test whether a serialized raw transaction would be accepted into the mempool.

        Validates the raw transaction hexadecimal string before calling the
        testmempoolaccept RPC method.

        :param raw_tx_hex: Raw transaction hex.
        :returns: The single result object returned by Bitcoin Core.
        :raises ValueError: If raw_tx_hex is invalid or the RPC returns an unexpected
                            shape.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        raw_tx_hex = validate_raw_tx_hex(raw_tx_hex)
        result = self.call("testmempoolaccept", [raw_tx_hex])
        if not isinstance(result, list) or len(result) != 1:
            raise ValueError("testmempoolaccept returned an unexpected result.")

        item = result[0]
        if not isinstance(item, dict):
            raise ValueError("testmempoolaccept result item was not a dict.")

        return item

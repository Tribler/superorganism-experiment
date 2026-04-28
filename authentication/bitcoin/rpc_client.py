from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from authentication.bitcoin.rpc_errors import BitcoinRpcError
from authentication.bitcoin.txid import validate_txid

SATOSHIS_PER_BTC = Decimal("100000000")


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

    @staticmethod
    def sats_to_btc_string(amount_sats: int) -> str:
        """
        Convert an amount in satoshis to a Bitcoin-denominated decimal string.

        The returned value is formatted with exactly 8 decimal places, which is the
        standard precision used for BTC amounts in Bitcoin RPC calls. The conversion uses
        Decimal arithmetic to avoid floating-point inaccuracies.

        :param amount_sats: The amount in satoshis. Must be non-negative.
        :return: A string representing the equivalent BTC amount, formatted for RPC use
                 (for example, 1500 -> "0.00001500").
        :raises ValueError: If amount_sats is negative.
        :raises BitcoinRpcError: If the underlying RPC call fails.
        """
        if amount_sats < 0:
            raise ValueError("amount_sats must be non-negative.")

        btc = (Decimal(amount_sats) / SATOSHIS_PER_BTC).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )
        return format(btc, "f")

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from authentication.bitcoin.rpc_errors import BitcoinRpcErrorCode
from authentication.transaction_verification.exceptions import TransactionFetchError
from authentication.transaction_verification.models import (
    NormalizedTransaction,
    NormalizedTxOutput,
)
from authentication.transaction_verification.base_verifier import BaseVerifier
from authentication.bitcoin.rpc_client import (
    BitcoinRpcClient,
    BitcoinRpcConfig,
    BitcoinRpcError,
)


class RpcVerifier(BaseVerifier):
    """
    Transaction verifier that retrieves transaction data from a Bitcoin Core RPC node.

    This verifier fetches decoded transactions through a BitcoinRpcClient, normalizes the
    RPC response into internal transaction models, and delegates the actual verification
    logic to BaseVerifier.
    """

    def __init__(self, rpc_client: BitcoinRpcClient) -> None:
        self._rpc_client = rpc_client

    @classmethod
    def from_config(cls, config: BitcoinRpcConfig) -> "RpcVerifier":
        """
        Create an RPC-based verifier from a Bitcoin RPC configuration.

        :param config: The RPC configuration used to construct the underlying client.
        :returns: A verifier backed by a configured BitcoinRpcClient.
        """
        return cls(rpc_client=BitcoinRpcClient.from_config(config))

    def close(self) -> None:
        """Close the underlying RPC client."""
        self._rpc_client.close()

    def _fetch_transaction(self, txid: str) -> NormalizedTransaction | None:
        """
        Fetch and normalize a transaction by its transaction ID.

        This method retrieves the decoded transaction from the RPC client and converts it
        into a NormalizedTransaction. If the transaction does not exist, None is returned.
        RPC and normalization failures are wrapped in TransactionFetchError.

        :param txid: The transaction ID to fetch.
        :returns: The normalized transaction, or None if the transaction was not found.
        :raises TransactionFetchError: If the RPC request fails for a reason other than a
                                       missing transaction, or if the RPC response cannot
                                       be normalized.
        """
        try:
            tx = self._rpc_client.get_raw_transaction(txid, verbosity=1)
        except BitcoinRpcError as exc:
            if exc.code == BitcoinRpcErrorCode.RPC_INVALID_ADDRESS_OR_KEY:
                return None
            raise TransactionFetchError(
                f"Failed to fetch transaction data: {exc}"
            ) from exc

        try:
            return self._normalize_transaction(tx)
        except ValueError as exc:
            raise TransactionFetchError(
                f"Failed to normalize transaction data: {exc}"
            ) from exc

    def _normalize_transaction(self, tx: dict[str, Any]) -> NormalizedTransaction:
        """
        Convert a raw transaction RPC response into a normalized transaction model.

        This method validates the expected structure of the decoded transaction, converts
        output amounts from BTC to satoshis, extracts destination addresses when
        available, and normalizes each output into a NormalizedTxOutput.

        :param tx: The decoded transaction object returned by the RPC client.
        :returns: A normalized transaction representation suitable for verification.
        :raises ValueError: If the RPC response is missing required fields or contains
                            values of an unexpected type.
        """
        txid_raw = tx.get("txid")
        if not isinstance(txid_raw, str) or not txid_raw.strip():
            raise ValueError("Invalid txid in RPC response.")

        confirmations_raw = tx.get("confirmations", 0)
        if isinstance(confirmations_raw, bool) or not isinstance(
            confirmations_raw, int
        ):
            raise ValueError("Invalid confirmations in RPC response.")
        confirmations = confirmations_raw

        vout_raw = tx.get("vout", [])
        if not isinstance(vout_raw, list):
            raise ValueError("Invalid vout in RPC response.")

        outputs: list[NormalizedTxOutput] = []
        for vout in vout_raw:
            if not isinstance(vout, dict):
                raise ValueError("Invalid vout entry in RPC response.")

            value_btc = vout.get("value")
            sats = self._btc_to_sats(value_btc)

            script_pub_key = vout.get("scriptPubKey")
            if not isinstance(script_pub_key, dict):
                raise ValueError("Invalid scriptPubKey in RPC response.")

            script_hex = script_pub_key.get("hex")
            if not isinstance(script_hex, str) or not script_hex.strip():
                raise ValueError("Invalid scriptPubKey hex in RPC response.")

            outputs.append(
                NormalizedTxOutput(
                    value_sats=sats,
                    address=self._extract_address(script_pub_key),
                    script_hex=script_hex,
                )
            )

        return NormalizedTransaction(
            txid=txid_raw,
            confirmations=confirmations,
            outputs=outputs,
        )

    @staticmethod
    def _extract_address(script_pub_key: dict[str, Any]) -> str | None:
        """
        Extract a destination address from a decoded scriptPubKey object.

        The method first checks the address field. If no non-empty string is present, it
        falls back to the first non-empty string in the addresses list, which may be used
        by some Bitcoin Core versions or contexts.

        :param script_pub_key: The decoded scriptPubKey object from an RPC response.
        :returns: The extracted address, or None if no usable address is present.
        """
        if "address" in script_pub_key:
            address = script_pub_key["address"]
            if not isinstance(address, str):
                raise ValueError("Invalid address in scriptPubKey.")
            address = address.strip()
            if address:
                return address

        # Some Core versions/contexts return an "addresses" array instead.
        if "addresses" in script_pub_key:
            addresses = script_pub_key["addresses"]
            if not isinstance(addresses, list):
                raise ValueError("Invalid addresses in scriptPubKey.")

            for candidate in addresses:
                if not isinstance(candidate, str):
                    raise ValueError("Invalid address entry in scriptPubKey addresses.")

            for candidate in addresses:
                candidate = candidate.strip()
                if candidate:
                    return candidate

        return None

    @staticmethod
    def _btc_to_sats(value_btc: Any) -> int:
        """
        Convert a BTC-denominated value to satoshis.

        The input may be an int, float, or str and must represent a value that can be
        converted exactly to a whole number of satoshis.

        :param value_btc: The BTC amount to convert.
        :returns: The equivalent amount in satoshis.
        :raises ValueError: If the value has an unsupported type, cannot be parsed as a
                            BTC amount, or is not exactly representable in satoshis.
        """
        if isinstance(value_btc, bool):
            raise ValueError(f"Invalid BTC amount in RPC response: {value_btc!r}")

        if not isinstance(value_btc, (int, float, str)):
            raise ValueError(f"Invalid BTC amount in RPC response: {value_btc!r}")

        try:
            sats_decimal = Decimal(str(value_btc)) * Decimal("100000000")
        except InvalidOperation as exc:
            raise ValueError(
                f"Invalid BTC amount in RPC response: {value_btc!r}"
            ) from exc

        if sats_decimal != sats_decimal.to_integral_value():
            raise ValueError(
                f"BTC amount is not representable in satoshis: {value_btc!r}"
            )

        return int(sats_decimal)

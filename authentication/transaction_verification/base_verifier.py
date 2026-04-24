from __future__ import annotations

from abc import ABC, abstractmethod

from authentication import constants as tx_constants
from authentication.transaction_verification.exceptions import TransactionFetchError
from authentication.transaction_verification.models import (
    TransactionVerificationRequest,
    TransactionVerificationResult,
    NormalizedTransaction,
)
from authentication.transaction_verification.transaction_verifier import (
    TransactionVerifier,
)


class BaseVerifier(TransactionVerifier, ABC):
    """
    Shared transaction verification workflow for backend-specific verifiers.

    Subclasses implement _fetch_transaction() to retrieve and normalize transaction data
    from a concrete backend, returning None when the transaction does not exist and
    raising TransactionFetchError for expected fetch or normalization failures.

    The verify() method then applies the common registration checks:
    - the transaction exists
    - the transaction meets the global confirmation threshold
    - enough sats were paid to the expected treasury address
    - the expected registration commitment appears in an OP_RETURN output
    """

    @abstractmethod
    def _fetch_transaction(self, txid: str) -> NormalizedTransaction | None:
        """
        Fetch and normalize a transaction by txid.

        Implementations should return None when the transaction does not exist and raise
        TransactionFetchError for backend transport, response-shape, or normalization
        failures.
        """
        raise NotImplementedError

    def verify(
        self,
        request: TransactionVerificationRequest,
    ) -> TransactionVerificationResult:
        """
        Verify that a transaction satisfies the registration payment requirements.

        The transaction is fetched and checked for existence, sufficient
        confirmations, a sufficient payment to the expected treasury address, and
        the presence of the expected registration commitment in an ``OP_RETURN``
        output.

        :param request: The expected transaction properties to verify against.
        :type request: TransactionVerificationRequest
        :returns: A verification result describing whether the transaction is valid
                  and, if not, why verification failed.
        :rtype: TransactionVerificationResult
        """
        try:
            tx = self._fetch_transaction(request.txid)
        except TransactionFetchError as exc:
            return TransactionVerificationResult(
                success=False,
                reason=f"Transaction verification failed: {exc}",
            )

        if tx is None:
            return TransactionVerificationResult(
                success=False,
                reason="Transaction not found.",
            )

        if tx.confirmations < tx_constants.MIN_CONFIRMATIONS:
            return TransactionVerificationResult(
                success=False,
                reason="Transaction does not have enough confirmations.",
                confirmations=tx.confirmations,
            )

        amount_paid_sats = self._sum_outputs_for_address(
            tx=tx,
            address=request.expected_treasury_address,
        )

        if amount_paid_sats < request.expected_fee_sats:
            return TransactionVerificationResult(
                success=False,
                reason="Transaction paid too little to the treasury address.",
                confirmations=tx.confirmations,
                amount_paid_sats=amount_paid_sats,
            )

        if not self._contains_registration_commitment(
            tx=tx,
            expected_commitment=request.expected_registration_commitment,
        ):
            return TransactionVerificationResult(
                success=False,
                reason="Transaction does not contain the expected registration commitment.",
                confirmations=tx.confirmations,
                amount_paid_sats=amount_paid_sats,
            )

        return TransactionVerificationResult(
            success=True,
            reason=None,
            amount_paid_sats=amount_paid_sats,
            confirmations=tx.confirmations,
        )

    @staticmethod
    def _sum_outputs_for_address(tx: NormalizedTransaction, address: str) -> int:
        """
        Sum the value of all transaction outputs sent to the given address.

        :param tx: The normalized transaction to inspect.
        :param address: The address to match against transaction outputs.
        :returns: The total value, in satoshis, of all outputs to the address.
        """
        return sum(
            output.value_sats for output in tx.outputs if output.address == address
        )

    @staticmethod
    def _contains_registration_commitment(
        tx: NormalizedTransaction,
        expected_commitment: str,
    ) -> bool:
        """
        Check whether a transaction contains the expected registration commitment.

        The expected commitment is normalized to lowercase hexadecimal and compared
        against the payload of each OP_RETURN output in the transaction. Outputs that are
        not OP_RETURN scripts or whose payload cannot be parsed are ignored.

        :param tx: The normalized transaction to inspect.
        :param expected_commitment: The expected commitment as a hex string.
        :returns: True if a matching commitment is found, otherwise False.
        """
        normalized_expected = expected_commitment.strip().lower()

        if not normalized_expected:
            return False
        try:
            bytes.fromhex(normalized_expected)
        except ValueError:
            return False

        for output in tx.outputs:
            if not output.script_hex.strip().lower().startswith("6a"):
                continue

            payload_hex = BaseVerifier._extract_op_return_payload_hex(output.script_hex)
            if payload_hex is None:
                continue

            if payload_hex == normalized_expected:
                return True

        return False

    @staticmethod
    def _extract_op_return_payload_hex(script_hex: str) -> str | None:
        """
        Extract the data payload from a minimally encoded OP_RETURN script.

        This helper expects a script of the form:

        - 6a <pushopcode> <payload>

        where 6a is OP_RETURN and the remainder consists of exactly one data push with no
        trailing bytes or additional opcodes.

        Supported push forms are:

        - OP_0 for an empty payload
        - direct push lengths 0x01 .. 0x4b
        - OP_PUSHDATA1 (0x4c)
        - OP_PUSHDATA2 (0x4d)
        - OP_PUSHDATA4 (0x4e)

        The returned payload is normalized to lowercase hexadecimal. If the script is not
        valid hex, is not an OP_RETURN script, does not match the expected single-push
        structure, or contains inconsistent length encoding, None is returned.

        :param script_hex: The output script in hexadecimal form.
        :returns: The pushed payload as lowercase hexadecimal, or None if parsing fails.
        """
        script_hex = script_hex.strip().lower()

        if len(script_hex) % 2 != 0:
            return None

        if not script_hex.startswith("6a"):
            return None

        cursor = 2
        if len(script_hex) < cursor + 2:
            return None

        try:
            opcode = int(script_hex[cursor : cursor + 2], 16)
        except ValueError:
            return None

        cursor += 2

        if opcode == 0x00:
            payload_len_bytes = 0
        elif 0x01 <= opcode <= 0x4B:
            payload_len_bytes = opcode
        elif opcode == 0x4C:  # OP_PUSHDATA1
            if len(script_hex) < cursor + 2:
                return None
            try:
                payload_len_bytes = int(script_hex[cursor : cursor + 2], 16)
            except ValueError:
                return None
            cursor += 2
        elif opcode == 0x4D:  # OP_PUSHDATA2
            if len(script_hex) < cursor + 4:
                return None
            length_hex_le = script_hex[cursor : cursor + 4]
            try:
                payload_len_bytes = int.from_bytes(
                    bytes.fromhex(length_hex_le), "little"
                )
            except ValueError:
                return None
            cursor += 4
        elif opcode == 0x4E:  # OP_PUSHDATA4
            if len(script_hex) < cursor + 8:
                return None
            length_hex_le = script_hex[cursor : cursor + 8]
            try:
                payload_len_bytes = int.from_bytes(
                    bytes.fromhex(length_hex_le), "little"
                )
            except ValueError:
                return None
            cursor += 8
        else:
            return None

        payload_len_hex = payload_len_bytes * 2
        if len(script_hex) != cursor + payload_len_hex:
            return None

        payload_hex = script_hex[cursor : cursor + payload_len_hex]
        try:
            bytes.fromhex(payload_hex)
        except ValueError:
            return None

        return payload_hex

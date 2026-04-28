from __future__ import annotations

from datetime import datetime, timezone

from authentication.bitcoin.txid import validate_txid
from authentication.identity.models import ApplicationIdentity
from authentication.models.registration_models import (
    RegistrationResult,
    StoredRegistration,
)
from authentication.transaction_verification.models import TransactionVerificationRequest
from authentication.storage.registration_store import RegistrationStore
from authentication.transaction_verification.transaction_verifier import TransactionVerifier


class RegistrationService:
    """
    Service responsible for registering application identities after payment verification.

    It coordinates transaction verification, duplicate-registration checks, and
    persistence of successful registrations in the registration store.
    """

    def __init__(
        self,
        transaction_verifier: TransactionVerifier,
        registration_store: RegistrationStore,
        expected_treasury_address: str,
        expected_fee_sats: int,
    ) -> None:
        self._transaction_verifier = transaction_verifier
        self._registration_store = registration_store
        self._expected_treasury_address = expected_treasury_address
        self._expected_fee_sats = expected_fee_sats

    def register(self, identity: ApplicationIdentity, txid: str) -> RegistrationResult:
        """
        Register an application identity after verifying its payment transaction.

        The transaction ID is first validated, then the registration store is checked to
        ensure the public key is not already registered. If the key is new, the
        transaction is verified against the expected treasury address, fee amount, and
        registration commitment. On success, the registration is persisted and a
        successful result is returned.

        :param identity: The application identity to register.
        :param txid: The transaction ID provided for registration.
        :returns: A result describing whether registration succeeded and, if not,
                  why it failed.
        """

        try:
            normalized_txid = validate_txid(txid)
        except ValueError:
            return RegistrationResult(
                success=False,
                public_key_hex=identity.public_key_hex,
                reason="Transaction ID must be a 64-character hexadecimal string.",
            )

        existing = self._registration_store.get(identity.public_key_hex)
        if existing is not None:
            return RegistrationResult(
                success=False,
                public_key_hex=identity.public_key_hex,
                reason="Public key is already registered.",
                txid=existing.txid,
                registered_at=existing.registered_at,
            )

        tx_result = self._transaction_verifier.verify(
            TransactionVerificationRequest(
                txid=normalized_txid,
                expected_treasury_address=self._expected_treasury_address,
                expected_fee_sats=self._expected_fee_sats,
                expected_registration_commitment=identity.registration_commitment_hex,
            )
        )

        if not tx_result.success:
            return RegistrationResult(
                success=False,
                public_key_hex=identity.public_key_hex,
                reason=tx_result.reason,
            )

        registered_at = datetime.now(timezone.utc)
        stored = StoredRegistration(
            public_key_hex=identity.public_key_hex,
            private_key_hex=identity.private_key_hex,
            txid=normalized_txid,
            registered_at=registered_at,
        )
        self._registration_store.save(stored)

        return RegistrationResult(
            success=True,
            public_key_hex=identity.public_key_hex,
            reason=None,
            txid=normalized_txid,
            registered_at=registered_at,
        )

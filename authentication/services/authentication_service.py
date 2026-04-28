from __future__ import annotations

import secrets
from datetime import datetime, timezone

from authentication.bitcoin.txid import validate_txid
from authentication.constants import (
    AUTHENTICATION_PROTOCOL_LABEL,
)
from authentication.crypto.ed25519_message_signer import Ed25519MessageSigner
from authentication.hex_utils import normalize_hex_string
from authentication.crypto.signature_verifier import SignatureVerifier
from authentication.models.authentication_models import (
    AuthenticationResult,
    StoredChallenge,
    VerifyRequest,
)
from authentication.registration_commitment_utils import compute_registration_commitment
from authentication.transaction_verification.models import (
    TransactionVerificationRequest,
)
from authentication.storage.challenge_store import ChallengeStore
from authentication.transaction_verification.transaction_verifier import (
    TransactionVerifier,
)
from config import NETWORK_ID


class AuthenticationService:
    """
    Service responsible for challenge-based authentication of registered identities.

    It creates login challenges, verifies signatures over those challenges, and confirms
    the referenced registration transaction before completing login.
    """

    def __init__(
        self,
        challenge_store: ChallengeStore,
        signature_verifier: SignatureVerifier,
        transaction_verifier: TransactionVerifier,
        expected_treasury_address: str,
        expected_fee_sats: int,
    ) -> None:
        self._challenge_store = challenge_store
        self._signature_verifier = signature_verifier
        self._transaction_verifier = transaction_verifier
        self._expected_treasury_address = expected_treasury_address
        self._expected_fee_sats = expected_fee_sats

    def create_challenge_message(self, public_key_hex: str) -> str:
        """
        Create and store a new authentication challenge message for a public key.

        The public key is normalized and validated, a fresh nonce and issuance time are
        generated, and the resulting challenge message is stored in the challenge store
        before being returned.

        :param public_key_hex: The public key for which to create a challenge.
        :returns: The generated challenge message to be signed.
        :raises ValueError: If the public key is empty after normalization.
        """
        normalized_public_key_hex = normalize_hex_string(public_key_hex)
        if not normalized_public_key_hex:
            raise ValueError("Public key must not be empty.")

        issued_at = datetime.now(timezone.utc)
        nonce = secrets.token_hex(16)

        message = self._build_message(
            public_key_hex=normalized_public_key_hex,
            nonce=nonce,
            issued_at=issued_at,
        )

        challenge = StoredChallenge(
            public_key_hex=normalized_public_key_hex,
            message=message,
            issued_at=issued_at,
        )

        self._challenge_store.save(challenge)

        return message

    def sign_outstanding_challenge(
        self, public_key_hex: str, private_key_hex: str
    ) -> bytes:
        """
        Sign the currently stored challenge message for a public key.

        This helper looks up the active challenge for the given public key, checks that it
        is still valid, and signs its message using the provided private key.

        Note: This method is intended only for prototyping and local development. In a
        real deployment, challenge messages should be signed by the client that holds the
        private key, rather than by the service itself.

        :param public_key_hex: The public key whose outstanding challenge should be
                               signed.
        :param private_key_hex: The private key used to sign the stored challenge message.
        :returns: The generated signature bytes.
        :raises ValueError: If either key is empty after normalization, if no active
                            challenge exists for the public key, or if the challenge
                            has expired.
        """
        normalized_public_key_hex = normalize_hex_string(public_key_hex)
        if not normalized_public_key_hex:
            raise ValueError("Public key must not be empty.")

        normalized_private_key_hex = normalize_hex_string(private_key_hex)
        if not normalized_private_key_hex:
            raise ValueError("Private key must not be empty.")

        stored = self._challenge_store.get(normalized_public_key_hex)
        if stored is None:
            raise ValueError("No active challenge found.")

        signer = Ed25519MessageSigner.from_private_key_hex(normalized_private_key_hex)
        return signer.sign_message(stored.message.encode("utf-8"))

    def verify_login(self, request: VerifyRequest) -> AuthenticationResult:
        """
        Verify a login request using the stored challenge, signature, and registration
        transaction.

        This method validates and normalizes the request fields, loads the active
        challenge for the provided public key, verifies the submitted signature over that
        challenge, and then checks that the referenced transaction satisfies the expected
        registration requirements. The challenge is deleted only after the full login flow
        succeeds.

        :param request: The login verification request containing the public key,
                        transaction ID, and signature.
        :returns: An authentication result indicating whether login succeeded and, if not,
                  why it failed.
        """

        # Normalize and validate request fields.
        normalized_public_key_hex = normalize_hex_string(request.public_key_hex)
        if not normalized_public_key_hex:
            return AuthenticationResult(False, "Public key must not be empty.")

        try:
            normalized_txid = validate_txid(request.txid)
        except ValueError:
            return AuthenticationResult(
                False,
                "Transaction ID must be a 64-character hexadecimal string.",
            )

        # Load the active challenge for this key.
        stored = self._challenge_store.get(normalized_public_key_hex)
        if stored is None:
            return AuthenticationResult(False, "No active challenge found.")

        # Prepare the public-key-based verification inputs.
        try:
            verifier = self._signature_verifier.from_public_key_hex(
                normalized_public_key_hex
            )
            public_key_bytes = bytes.fromhex(normalized_public_key_hex)
        except ValueError:
            return AuthenticationResult(False, "Public key must be valid hex.")

        expected_commitment = compute_registration_commitment(public_key_bytes)

        # Verify the signed challenge before any external transaction check.
        try:
            is_valid = verifier.verify_signature(
                message=stored.message.encode("utf-8"),
                signature=request.signature,
            )
        except Exception as exc:
            return AuthenticationResult(False, f"Signature verification failed: {exc}")

        if not is_valid:
            return AuthenticationResult(False, "Invalid signature.")

        # Verify the registration transaction against the expected commitment.
        tx_result = self._transaction_verifier.verify(
            TransactionVerificationRequest(
                txid=normalized_txid,
                expected_treasury_address=self._expected_treasury_address,
                expected_fee_sats=self._expected_fee_sats,
                expected_registration_commitment=expected_commitment,
            )
        )

        if not tx_result.success:
            return AuthenticationResult(
                False,
                tx_result.reason or "Transaction verification failed.",
            )

        # Consume the challenge only after full verification succeeds.
        self._challenge_store.delete(normalized_public_key_hex)

        return AuthenticationResult(True, None)

    @staticmethod
    def _build_message(
        public_key_hex: str,
        nonce: str,
        issued_at: datetime,
    ) -> str:
        return "\n".join(
            [
                f"protocol={AUTHENTICATION_PROTOCOL_LABEL.decode('ascii')}",
                f"network={NETWORK_ID.decode('ascii')}",
                "action=login",
                f"public_key_hex={public_key_hex}",
                f"nonce={nonce}",
                f"issued_at={issued_at.isoformat()}",
            ]
        )

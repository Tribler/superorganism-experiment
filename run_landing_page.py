from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from authentication.crypto.ed25519_signature_verifier import Ed25519SignatureVerifier
from authentication.services.authentication_service import AuthenticationService
from authentication.services.registration_service import RegistrationService
from authentication.storage.in_memory_challenge_store import InMemoryChallengeStore
from authentication.storage.json_registration_store import JsonRegistrationStore
from authentication.transaction_verification.rpc_verifier import RpcVerifier
from config import REGTEST_RPC_CONFIG
from ui.common.fonts import load_application_fonts
from ui.landing.landing_page import LandingPageWidget


def main() -> None:
    root_path = Path(__file__).resolve().parent

    env_path = root_path / ".bitcoin" / ".env.regtest"
    load_dotenv(env_path)

    payment_address = os.environ.get("TREASURY_ADDRESS")
    if not payment_address:
        raise RuntimeError(
            f"TREASURY_ADDRESS is missing. Expected it in {env_path}"
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Superorganism Landing Page")
    load_application_fonts()

    qss_paths = [
        root_path / "ui" / "styles" / "main.qss",
        root_path / "ui" / "landing" / "landing_page.qss",
    ]

    stylesheet = "\n\n".join(
        qss_path.read_text(encoding="utf-8")
        for qss_path in qss_paths
        if qss_path.exists()
    )
    app.setStyleSheet(stylesheet)

    transaction_verifier = RpcVerifier.from_config(REGTEST_RPC_CONFIG)
    registration_store = JsonRegistrationStore(".superorganism/registrations.json")

    registration_service = RegistrationService(
        transaction_verifier=transaction_verifier,
        registration_store=registration_store,
        expected_treasury_address=payment_address,
        expected_fee_sats=1000,
    )

    challenge_store = InMemoryChallengeStore()
    authentication_service = AuthenticationService(
        challenge_store=challenge_store,
        signature_verifier=Ed25519SignatureVerifier,
        expected_treasury_address=payment_address,
        transaction_verifier=transaction_verifier,
        expected_fee_sats=1000,
    )


    widget = LandingPageWidget(
        registration_service=registration_service,
        registration_store=registration_store,
        authentication_service=authentication_service,
        payment_address=payment_address,
    )
    widget.resize(1440, 1100)
    widget.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

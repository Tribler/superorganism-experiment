"""
Watch-only Bitcoin wallet for balance monitoring.

This module provides a watch-only wallet using the extended public key (xpub).
It can monitor balance and derive addresses but CANNOT spend funds.

This is intentionally limited for security - no private keys on the VPS.
"""

import logging
from typing import Optional

from bitcoinlib.wallets import Wallet, wallet_exists, wallet_delete

from config import Config
from utils import setup_logger

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class WalletError(Exception):
    """Base exception for wallet operations."""
    pass


class WatchOnlyWallet:
    """
    Watch-only Bitcoin wallet for balance monitoring.

    This wallet uses only the extended public key (xpub) and can:
    - Monitor balance
    - Derive receiving addresses
    - Scan for incoming payments

    It CANNOT:
    - Send transactions
    - Access private keys

    This is the secure approach for VPS deployment - even if the server
    is compromised, the attacker cannot spend funds.
    """

    def __init__(
        self,
        wallet_name: str = None,
        xpub: str = None,
        network: str = "bitcoin",
        db_uri: Optional[str] = None
    ):
        """
        Initialize watch-only wallet.

        Args:
            wallet_name: Name for the wallet (default from config)
            xpub: Extended public key (default from config)
            network: Bitcoin network ('bitcoin' for mainnet)
            db_uri: Optional SQLite database URI
        """
        self.wallet_name = wallet_name or Config.BITCOIN_WALLET_NAME
        self.xpub = xpub or Config.BITCOIN_XPUB
        self.network = network or Config.BITCOIN_NETWORK
        self.db_uri = db_uri

        self._wallet: Optional[Wallet] = None

    @property
    def wallet(self) -> Wallet:
        """Get the loaded wallet, raising if not loaded."""
        if self._wallet is None:
            raise WalletError("Wallet not loaded. Call create_from_xpub() first.")
        return self._wallet

    @property
    def is_configured(self) -> bool:
        """Check if xpub is configured."""
        return bool(self.xpub)

    def exists(self) -> bool:
        """Check if wallet already exists."""
        return wallet_exists(self.wallet_name, db_uri=self.db_uri)

    def create_from_xpub(self, xpub: str = None) -> None:
        """
        Create or load watch-only wallet from extended public key.

        Args:
            xpub: Extended public key (uses config if not provided)

        Raises:
            WalletError: If xpub is not provided and not in config
        """
        xpub = xpub or self.xpub

        if not xpub:
            raise WalletError(
                "No xpub provided. Set MYCELIUM_BITCOIN_XPUB environment variable "
                "or pass xpub parameter."
            )

        if self.exists():
            logger.info(f"Loading existing wallet: {self.wallet_name}")
            self._wallet = Wallet(self.wallet_name, db_uri=self.db_uri)
        else:
            logger.info(f"Creating watch-only wallet: {self.wallet_name}")
            self._wallet = Wallet.create(
                self.wallet_name,
                keys=xpub,
                network=self.network,
                db_uri=self.db_uri,
                witness_type="segwit"  # Use native segwit for lower fees
            )

        logger.info(f"Wallet ready. Balance: {self.get_balance_btc()} BTC")

    def delete(self) -> None:
        """Delete the wallet database."""
        if self.exists():
            logger.warning(f"Deleting wallet: {self.wallet_name}")
            wallet_delete(self.wallet_name, db_uri=self.db_uri, force=True)
            self._wallet = None

    def scan(self) -> None:
        """
        Scan blockchain for transactions and update balance.

        Call this periodically to check for incoming payments.
        """
        logger.info("Scanning blockchain for transactions...")
        self.wallet.scan()
        logger.info(f"Scan complete. Balance: {self.get_balance_btc()} BTC")

    def get_balance_satoshis(self) -> int:
        """Get confirmed balance in satoshis."""
        return self.wallet.balance()

    def get_balance_btc(self) -> float:
        """Get confirmed balance in BTC."""
        return self.get_balance_satoshis() / 100_000_000

    def get_receiving_address(self) -> str:
        """
        Get a receiving address.

        Even watch-only wallets can derive new addresses from xpub.

        Returns:
            A Bitcoin address string
        """
        key = self.wallet.get_key()
        return key.address

    def info(self) -> dict:
        """
        Get wallet information.

        Returns:
            Dict with wallet details
        """
        return {
            "name": self.wallet_name,
            "network": self.network,
            "watch_only": True,
            "balance_satoshis": self.get_balance_satoshis(),
            "balance_btc": self.get_balance_btc(),
            "receiving_address": self.get_receiving_address(),
        }


def get_wallet() -> Optional[WatchOnlyWallet]:
    """
    Get configured wallet instance.

    Returns:
        WatchOnlyWallet if configured, None otherwise
    """
    wallet = WatchOnlyWallet()

    if not wallet.is_configured:
        logger.debug("Bitcoin wallet not configured (no MYCELIUM_BITCOIN_XPUB)")
        return None

    try:
        wallet.create_from_xpub()
        return wallet
    except WalletError as e:
        logger.error(f"Failed to initialize wallet: {e}")
        return None


if __name__ == "__main__":
    # Simple test
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python wallet.py <xpub>")
        print("Or set MYCELIUM_BITCOIN_XPUB environment variable")
        sys.exit(1)

    xpub = sys.argv[1] if len(sys.argv) > 1 else None

    wallet = WatchOnlyWallet(wallet_name="test_wallet", xpub=xpub)
    wallet.create_from_xpub()

    print(f"Wallet info: {wallet.info()}")

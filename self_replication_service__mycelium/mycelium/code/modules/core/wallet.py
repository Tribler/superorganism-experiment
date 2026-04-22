"""
Local spending Bitcoin wallet for autonomous node operations.

On first boot: creates wallet from MYCELIUM_BTC_MNEMONIC env var,
persists mnemonic to disk (chmod 600), and removes the env var from
/etc/environment. On subsequent boots: loads wallet DB from disk directly.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from bitcoinlib.wallets import Wallet

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


def _remove_from_etc_environment(key: str) -> None:
    """Remove a KEY=... line from /etc/environment, ignoring errors."""
    env_file = Path("/etc/environment")
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text().splitlines()
        filtered = [line for line in lines if not line.startswith(f"{key}=")]
        tmp = env_file.with_suffix(".tmp")
        tmp.write_text("\n".join(filtered) + "\n")
        tmp.chmod(0o644)
        tmp.replace(env_file)
        logger.info("Removed %s from /etc/environment", key)
    except Exception as e:
        logger.warning("Could not remove %s from /etc/environment: %s", key, e)


class SpendingWallet:
    """
    Full spending Bitcoin wallet stored locally on the VPS.

    Holds the private key on disk in a bitcoinlib wallet DB.
    The mnemonic is also persisted to mnemonic.txt (chmod 600).
    """

    def __init__(self, wallet: Wallet):
        self._wallet = wallet

    def get_receiving_address(self) -> str:
        """Get a receiving address for this wallet."""
        key = self._wallet.get_key()
        return key.address

    def get_balance_satoshis(self) -> int:
        """Get confirmed balance in satoshis."""
        return self._wallet.balance()

    def get_balance_btc(self) -> float:
        """Get confirmed balance in BTC."""
        return self.get_balance_satoshis() / 100_000_000

    def scan(self) -> None:
        """Scan blockchain for transactions and update balance."""
        logger.info("Scanning blockchain for transactions...")
        self._wallet.scan()
        logger.info("Scan complete. Balance: %s BTC", self.get_balance_btc())

    def send(self, address: str, amount_satoshis: int, fee=None) -> str:
        """Send Bitcoin to address. Returns txid."""
        from bitcoinlib.services.services import Service

        balance = self.get_balance_satoshis()
        if balance < amount_satoshis:
            raise WalletError(
                f"Insufficient funds. Balance: {balance} sat, "
                f"Required: {amount_satoshis} sat"
            )

        logger.info("Sending %d sat to %s", amount_satoshis, address)
        tx = self._wallet.send_to(address, amount_satoshis, fee=fee, broadcast=False)

        if not tx.verified:
            raise WalletError(f"Transaction verification failed: {tx.error}")

        srv = Service(network=Config.BITCOIN_NETWORK)
        result = srv.sendrawtransaction(tx.raw_hex())

        if result and result.get("txid"):
            logger.info("Transaction sent: %s", tx.txid)
            return tx.txid

        raise WalletError(f"Broadcast failed: {result}")

    def sweep_all(self, address: str, fee_per_kb: int = None) -> str:
        """Send entire balance to address, fee auto-calculated by bitcoinlib. Returns txid."""
        tx = self._wallet.sweep(address, broadcast=True, fee_per_kb=fee_per_kb)
        if not tx or not tx.txid:
            raise WalletError(f"Sweep failed: {getattr(tx, 'error', 'unknown error')}")
        logger.info("Sweep complete: %s", tx.txid)
        return tx.txid


# Module-level singleton
_wallet_instance: Optional[SpendingWallet] = None


def initialize_wallet() -> None:
    """
    Initialize the spending wallet singleton.

    First boot (no wallet DB): reads mnemonic from MYCELIUM_BTC_MNEMONIC
    env var, creates wallet, writes mnemonic.txt (chmod 600), removes
    env var from /etc/environment.

    Subsequent boots: loads wallet DB from disk directly.
    """
    global _wallet_instance

    name = Config.BITCOIN_WALLET_NAME
    network = Config.BITCOIN_NETWORK
    wallet_db = Config.DATA_DIR / f"{name}.db"
    mnemonic_file = Config.DATA_DIR / "mnemonic.txt"
    db_uri = f"sqlite:///{wallet_db}"

    mnemonic_seed_file = Config.DATA_DIR / "btc_mnemonic_seed"

    try:
        if wallet_db.exists():
            logger.info("Loading wallet from existing DB...")
            if mnemonic_seed_file.exists():
                mnemonic_seed_file.unlink()
                logger.info("Cleaned up stale btc_mnemonic_seed")
            raw = Wallet(name, db_uri=db_uri)
        else:
            if mnemonic_seed_file.exists():
                mnemonic = mnemonic_seed_file.read_text().strip()
            else:
                mnemonic = os.environ.get("MYCELIUM_BTC_MNEMONIC") or Config.BTC_MNEMONIC
            if not mnemonic:
                logger.warning(
                    "No wallet DB and no MYCELIUM_BTC_MNEMONIC — wallet not configured"
                )
                return

            from bitcoinlib.mnemonic import Mnemonic as _Mnemonic
            try:
                _Mnemonic().to_entropy(mnemonic)
            except Exception:
                raise WalletError("Invalid BIP39 mnemonic — check seed file or MYCELIUM_BTC_MNEMONIC")

            logger.info("First boot: creating wallet from mnemonic...")
            raw = Wallet.create(
                name,
                keys=mnemonic,
                network=network,
                db_uri=db_uri,
                witness_type="segwit"
            )

            if wallet_db.exists():
                wallet_db.chmod(0o600)

            if mnemonic_seed_file.exists():
                mnemonic_seed_file.unlink()

            fd = os.open(str(mnemonic_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, mnemonic.encode())
            finally:
                os.close(fd)
            logger.info("Mnemonic persisted to %s (mode 600)", mnemonic_file)

            _remove_from_etc_environment("MYCELIUM_BTC_MNEMONIC")
            os.environ.pop("MYCELIUM_BTC_MNEMONIC", None)

        _wallet_instance = SpendingWallet(raw)
        logger.info("Wallet ready. Address: %s", _wallet_instance.get_receiving_address())

    except Exception as e:
        logger.error("Failed to initialize wallet: %s", e)
        _wallet_instance = None


def get_wallet() -> Optional[SpendingWallet]:
    """Return the wallet singleton, or None if not configured."""
    return _wallet_instance

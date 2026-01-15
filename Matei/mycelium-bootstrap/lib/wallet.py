"""Bitcoin wallet management for autonomous VPS provisioning."""

import logging
from pathlib import Path
from typing import Optional

from bitcoinlib.mnemonic import Mnemonic
from bitcoinlib.wallets import Wallet, wallet_exists, wallet_delete

logger = logging.getLogger(__name__)


class WalletError(Exception):
    """Base exception for wallet operations."""
    pass


class InsufficientFundsError(WalletError):
    pass


class BitcoinWallet:
    """Full Bitcoin wallet with spending capability."""

    DEFAULT_WALLET_DIR = Path.home() / ".mycelium" / "wallets"

    def __init__(
        self,
        wallet_name: str,
        network: str = "bitcoin",
        db_uri: Optional[str] = None
    ):
        self.wallet_name = wallet_name
        self.network = network
        self.db_uri = db_uri
        self._wallet: Optional[Wallet] = None

        self.DEFAULT_WALLET_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def wallet(self) -> Wallet:
        if self._wallet is None:
            raise WalletError("Wallet not loaded. Call create_new() or load() first.")
        return self._wallet

    def exists(self) -> bool:
        return wallet_exists(self.wallet_name, db_uri=self.db_uri)

    def create_new(self) -> str:
        """Create a new HD wallet. Returns the mnemonic phrase."""
        if self.exists():
            raise WalletError(
                f"Wallet '{self.wallet_name}' already exists. "
                "Use load() to open it or delete it first."
            )

        logger.info(f"Creating new wallet: {self.wallet_name}")

        mnemonic = Mnemonic().generate()

        self._wallet = Wallet.create(
            self.wallet_name,
            keys=mnemonic,
            network=self.network,
            db_uri=self.db_uri,
            witness_type="segwit"
        )

        logger.warning(
            "IMPORTANT: Save your mnemonic phrase securely! "
            "It is the ONLY way to recover your wallet."
        )

        return mnemonic

    def load(self) -> None:
        if not self.exists():
            raise WalletError(
                f"Wallet '{self.wallet_name}' does not exist. "
                "Use create_new() to create it."
            )

        logger.info(f"Loading wallet: {self.wallet_name}")
        self._wallet = Wallet(self.wallet_name, db_uri=self.db_uri)

    def restore_from_mnemonic(self, mnemonic: str) -> None:
        if self.exists():
            raise WalletError(
                f"Wallet '{self.wallet_name}' already exists. "
                "Delete it first with delete() method, then restore."
            )

        logger.info(f"Restoring wallet from mnemonic: {self.wallet_name}")
        self._wallet = Wallet.create(
            self.wallet_name,
            keys=mnemonic,
            network=self.network,
            db_uri=self.db_uri,
            witness_type="segwit"
        )

        self.scan()

    def delete(self) -> None:
        """Delete the wallet. Ensure mnemonic is backed up first."""
        if self.exists():
            logger.warning(f"Deleting wallet: {self.wallet_name}")
            wallet_delete(self.wallet_name, db_uri=self.db_uri, force=True)
            self._wallet = None

    def scan(self) -> None:
        """Scan blockchain for transactions and update wallet state."""
        logger.info("Scanning blockchain for transactions...")
        self.wallet.scan()
        self.wallet.utxos_update()
        logger.info(f"Scan complete. Balance: {self.get_balance_btc()} BTC")

    def get_balance_satoshis(self) -> int:
        return self.wallet.balance()

    def get_balance_btc(self) -> float:
        return self.get_balance_satoshis() / 100_000_000

    def get_receiving_address(self) -> str:
        key = self.wallet.get_key()
        return key.address

    def get_xpub(self) -> str:
        """Get the extended public key (xpub) for watch-only wallets."""
        from bitcoinlib.keys import HDKey

        main_key = self.wallet.main_key
        if main_key.wif:
            hdkey = HDKey(main_key.wif, network=self.network)
            return hdkey.wif_public()

        raise WalletError("Could not extract extended public key from wallet")

    def send(
        self,
        address: str,
        amount_satoshis: int,
        fee: Optional[int] = None
    ) -> str:
        """Send Bitcoin to an address. Returns txid."""
        from bitcoinlib.services.services import Service

        balance = self.get_balance_satoshis()
        if balance < amount_satoshis:
            raise InsufficientFundsError(
                f"Insufficient funds. Balance: {balance} sat, "
                f"Required: {amount_satoshis} sat"
            )

        logger.info(
            f"Sending {amount_satoshis} satoshis "
            f"({amount_satoshis / 100_000_000:.8f} BTC) to {address}"
        )

        try:
            tx = self.wallet.send_to(address, amount_satoshis, fee=fee, broadcast=False)

            if not tx.verified:
                raise WalletError(f"Transaction verification failed: {tx.error}")

            srv = Service(network=self.network)
            result = srv.sendrawtransaction(tx.raw_hex())

            if result and result.get('txid'):
                logger.info(f"Transaction sent successfully: {tx.txid}")
                return tx.txid
            else:
                raise WalletError(f"Broadcast failed: {result}")

        except WalletError:
            raise
        except Exception as e:
            raise WalletError(f"Transaction failed: {e}")

    def pay_sporestack_invoice(self, invoice: dict) -> str:
        """Pay a SporeStack invoice. Returns txid."""
        if 'payment_uri' in invoice:
            uri = invoice['payment_uri']
            if uri.startswith('bitcoin:'):
                parts = uri[8:].split('?')
                address = parts[0]
                amount_btc = None
                if len(parts) > 1:
                    params = dict(p.split('=') for p in parts[1].split('&'))
                    amount_btc = float(params.get('amount', 0))

                if amount_btc:
                    amount_satoshis = int(amount_btc * 100_000_000)
                else:
                    raise WalletError("Invoice missing amount")
            else:
                raise WalletError(f"Unsupported payment URI format: {uri}")
        else:
            address = invoice.get('address')
            amount_satoshis = invoice.get('amount_satoshis') or invoice.get('amount')

            if not address or not amount_satoshis:
                raise WalletError("Invoice must contain 'address' and 'amount'")

        logger.info(f"Paying SporeStack invoice: {amount_satoshis} sat to {address}")
        return self.send(address, amount_satoshis)

    def info(self) -> dict:
        return {
            "name": self.wallet_name,
            "network": self.network,
            "balance_satoshis": self.get_balance_satoshis(),
            "balance_btc": self.get_balance_btc(),
            "receiving_address": self.get_receiving_address(),
            "xpub": self.get_xpub(),
        }


def create_wallet_interactive() -> BitcoinWallet:
    wallet_name = input("Enter wallet name (default: mycelium): ").strip() or "mycelium"

    wallet = BitcoinWallet(wallet_name)

    if wallet.exists():
        print(f"Wallet '{wallet_name}' already exists.")
        wallet.load()
        print(f"Loaded wallet. Balance: {wallet.get_balance_btc()} BTC")
    else:
        print(f"Creating new wallet '{wallet_name}'...")
        mnemonic = wallet.create_new()
        print("\n" + "=" * 60)
        print("IMPORTANT: Save this mnemonic phrase securely!")
        print("It is the ONLY way to recover your wallet.")
        print("=" * 60)
        print(f"\n{mnemonic}\n")
        print("=" * 60 + "\n")

        print(f"Receiving address: {wallet.get_receiving_address()}")

    return wallet



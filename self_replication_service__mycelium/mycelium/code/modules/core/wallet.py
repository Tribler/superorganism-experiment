"""
Local spending Bitcoin wallet for autonomous node operations.

On first boot: creates wallet from MYCELIUM_BTC_MNEMONIC env var,
persists mnemonic to disk (chmod 600), and removes the env var from
/etc/environment. On subsequent boots: loads wallet DB from disk directly.
"""

import logging
import os
import threading
import time
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Optional, Tuple

from bitcoinlib.wallets import Wallet
import bitcoinlib.db as _bitcoinlib_db

from config import Config
from utils import setup_logger

# bitcoinlib creates its SQLAlchemy engine inside Db.__init__  the
# sqlite session is bound to the creatingthread.
# NodeMonitor.refresh runs on a ThreadPoolExecutor (asyncio.to_thread)
# bitcoinlib.db.create_engine adds check_same_thread=False;
_orig_create_engine = _bitcoinlib_db.create_engine

def _create_engine_thread_safe(url, *args, **kwargs):
    if isinstance(url, str) and url.startswith("sqlite:"):
        kwargs.setdefault("connect_args", {}).setdefault("check_same_thread", False)
    return _orig_create_engine(url, *args, **kwargs)

_bitcoinlib_db.create_engine = _create_engine_thread_safe


# Sim-only electrumx patches. Production uses HTTP providers and never hits these.
if Config.SIM_MODE:
    import asyncio as _asyncio
    import socket as _socket
    try:
        import aiorpcx as _aiorpcx
    except ImportError:
        _aiorpcx = None

    if _aiorpcx is not None:
        # ElectrumxClient.compose_request uses asyncio.get_event_loop() which fails
        # under asyncio.to_thread workers — every scan surfaces as ServiceError.
        from bitcoinlib.services.electrumx import ElectrumxClient as _ElectrumxClient
        from bitcoinlib.services.baseclient import ClientError as _ClientError

        def _electrumx_compose_request_thread_safe(self, method, parameters=None):
            try:
                host, port = self.base_url.split(':')
            except ValueError:
                raise _ClientError('Please specify ElectrumX uri in format host:port')
            parameters = parameters or []
            probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            probe.settimeout(2)
            try:
                if probe.connect_ex((host, int(port))) != 0:
                    raise _ClientError('ElectrumX server %s unavailable at port %s' % (host, port))
            finally:
                probe.close()

            async def _send():
                async with _aiorpcx.connect_rs(host, int(port),
                                               framer=_aiorpcx.NewlineFramer(5000000)) as session:
                    session.sent_request_timeout = self.timeout
                    return await session.send_request(method, parameters)

            loop = _asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_send())
            finally:
                loop.close()

        _ElectrumxClient.compose_request = _electrumx_compose_request_thread_safe

    # _parse_transaction does tx['confirmations'] which KeyErrors on mempool txs.
    from bitcoinlib.services.electrumx import ElectrumxClient as _EC2  # noqa: E402
    _orig_parse_transaction = _EC2._parse_transaction
    def _parse_transaction_safe(self, tx, *args, **kwargs):
        tx.setdefault("confirmations", 0)
        return _orig_parse_transaction(self, tx, *args, **kwargs)
    _EC2._parse_transaction = _parse_transaction_safe


_wallet_lock = threading.RLock()

# Sim-mode retry knobs for the pre-send UTXO refresh. Host's _scan_until_funded
# uses 20 attempts × 3s; we use a tighter cadence here because the parent's
# tx is already in mempool by the time send() runs, so the relevant lag is
# electrs's listunspent indexing, which is usually sub-second.
_SIM_SEND_SCAN_ATTEMPTS = 20
_SIM_SEND_SCAN_DELAY = 1.5
# Mirrors spawn_identity._ESTIMATED_FEE_SAT_MAX — the conservative fee buffer
# the caller's balance check already uses, kept in sync so we stop polling
# once we have enough confirmed UTXOs to actually build the tx.
_SIM_SEND_FEE_HEADROOM_SAT = 5_000


def _synchronized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _wallet_lock:
            return fn(*args, **kwargs)
    return wrapper

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class WalletError(Exception):
    """Base exception for wallet operations."""
    pass


def parse_bitcoin_uri(uri: str) -> Optional[Tuple[str, int]]:
    """Parse BIP-21 bitcoin:ADDRESS?amount=BTC → (address, amount_sat) or None."""
    if not uri.startswith("bitcoin:"):
        return None
    parts = uri[8:].split("?")
    address = parts[0]
    amount_btc_str = None
    if len(parts) > 1:
        for param in parts[1].split("&"):
            if param.startswith("amount="):
                amount_btc_str = param[7:]
                break
    if not address or amount_btc_str is None:
        return None
    # Decimal avoids float imprecision: int(float("0.0006") * 1e8) truncates to 59999.
    return address, int(Decimal(amount_btc_str) * 100_000_000)


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

    @_synchronized
    def get_receiving_address(self) -> str:
        """Get a receiving address for this wallet."""
        key = self._wallet.get_key()
        return key.address

    @_synchronized
    def get_balance_satoshis(self) -> int:
        """Get confirmed balance in satoshis."""
        return self._wallet.balance()

    @_synchronized
    def get_balance_btc(self) -> float:
        """Get confirmed balance in BTC."""
        return self.get_balance_satoshis() / 100_000_000

    @_synchronized
    def scan(self) -> None:
        """Scan blockchain for transactions and update balance."""
        logger.info("Scanning blockchain for transactions...")
        self._wallet.scan()
        logger.info("Scan complete. Balance: %s BTC", self.get_balance_btc())

    @_synchronized
    def send(self, address: str, amount_satoshis: int, fee=None) -> str:
        """Send Bitcoin to address. Returns txid."""
        if Config.SIM_MODE:
            # Sim issues many sends per minute; resync local UTXO table so coin
            # selection doesn't pick inputs already consumed by an earlier send.
            # scan() (not just transactions_update) is required: after a prior
            # send, the change tx sits in the local DB with block_height=None,
            # and transactions_update_confirmations filters on block_height>0,
            # so confirmations stay at 0 and select_inputs (min_confirms=1)
            # finds nothing. scan() re-fetches each confs==0 tx by txid, which
            # restores its block_height + confirmations from the indexer.
            #
            # Retry loop: electrs's address.listunspent can lag address.history
            # by seconds-to-tens-of-seconds, so a single scan+update sometimes
            # leaves utxos() empty even though balance() reports the funds.
            # Mirror run_simulation._scan_until_funded — poll until we see
            # confirmed UTXOs covering amount + fee headroom, or give up with
            # a clear error.
            needed = amount_satoshis + _SIM_SEND_FEE_HEADROOM_SAT
            last_err: Optional[Exception] = None
            for attempt in range(_SIM_SEND_SCAN_ATTEMPTS):
                try:
                    self._wallet.scan()
                    self._wallet.utxos_update(rescan_all=True)
                    utxos = self._wallet.utxos() or []
                    spendable = sum(
                        int(u.get("value", 0))
                        for u in utxos
                        if int(u.get("confirmations", 0)) >= 1
                    )
                    if spendable >= needed:
                        if attempt > 0:
                            logger.info(
                                "wallet ready after %d scan(s): %d confirmed utxo(s), %d sat spendable",
                                attempt + 1,
                                sum(1 for u in utxos if int(u.get("confirmations", 0)) >= 1),
                                spendable,
                            )
                        break
                    logger.info(
                        "wallet has %d utxo(s), %d sat spendable (< %d needed); scan %d/%d, retrying in %.1fs...",
                        len(utxos), spendable, needed,
                        attempt + 1, _SIM_SEND_SCAN_ATTEMPTS, _SIM_SEND_SCAN_DELAY,
                    )
                except Exception as e:
                    last_err = e
                    logger.warning(
                        "wallet refresh before send failed on attempt %d/%d: %s",
                        attempt + 1, _SIM_SEND_SCAN_ATTEMPTS, e,
                    )
                if attempt < _SIM_SEND_SCAN_ATTEMPTS - 1:
                    time.sleep(_SIM_SEND_SCAN_DELAY)
            else:
                # Loop exhausted without break — surface a clear error instead
                # of letting send_to raise bitcoinlib's misleading
                # "no key available for UTXO's" message.
                detail = f" (last error: {last_err})" if last_err else ""
                raise WalletError(
                    f"No spendable UTXOs covering {needed} sat after "
                    f"{_SIM_SEND_SCAN_ATTEMPTS} scan attempts — electrs may be "
                    f"stalled or mempool tx unmined{detail}"
                )

        balance = self.get_balance_satoshis()
        if balance < amount_satoshis:
            raise WalletError(
                f"Insufficient funds. Balance: {balance} sat, "
                f"Required: {amount_satoshis} sat"
            )

        logger.info("Sending %d sat to %s", amount_satoshis, address)
        if Config.SIM_MODE:
            # broadcast=True so bitcoinlib marks spent UTXOs in the local DB.
            tx = self._wallet.send_to(address, amount_satoshis, fee=fee, broadcast=True)
            if not tx.verified:
                raise WalletError(f"Transaction verification failed: {tx.error}")
            if not tx.txid:
                raise WalletError(f"Broadcast failed: {getattr(tx, 'error', 'unknown error')}")
            logger.info("Transaction sent: %s", tx.txid)
            return tx.txid

        from bitcoinlib.services.services import Service
        tx = self._wallet.send_to(address, amount_satoshis, fee=fee, broadcast=False)
        if not tx.verified:
            raise WalletError(f"Transaction verification failed: {tx.error}")
        srv = Service(network=Config.BITCOIN_NETWORK)
        result = srv.sendrawtransaction(tx.raw_hex())
        if result and result.get("txid"):
            logger.info("Transaction sent: %s", tx.txid)
            return tx.txid
        raise WalletError(f"Broadcast failed: {result}")

    @_synchronized
    def sweep_all(self, address: str, fee_per_kb: int = None) -> str:
        """Send entire balance to address, fee auto-calculated by bitcoinlib. Returns txid."""
        tx = self._wallet.sweep(address, broadcast=True, fee_per_kb=fee_per_kb)
        if not tx or not tx.txid:
            raise WalletError(f"Sweep failed: {getattr(tx, 'error', 'unknown error')}")
        logger.info("Sweep complete: %s", tx.txid)
        return tx.txid


# How long to keep re-querying the indexer before we accept "no prior tx exists"
# on a reconcile path. Mempool propagation on signet/testnet can lag well beyond
# the bitcoinlib transactions_update default; without this poll a freshly
# broadcast tx that hasn't reached the indexer yet would be re-broadcast,
# double-paying.
_RECONCILE_POLL_TIMEOUT_SECONDS = 90
_RECONCILE_POLL_INTERVAL_SECONDS = 10


def scan_for_prior_send(
    wallet: "SpendingWallet",
    address: str,
    amount_sat: int,
) -> Optional[str]:
    """One pass over bitcoinlib's stored transactions; returns matching outbound txid or None."""
    try:
        wallet._wallet.transactions_update()
    except Exception as e:
        logger.warning("transactions_update failed during reconcile: %s", e)

    try:
        txs = wallet._wallet.transactions_full()
    except Exception as e:
        logger.warning("transactions_full failed during reconcile: %s", e)
        return None

    for tx in txs or []:
        if not getattr(tx, "is_send", True):
            continue
        outputs = getattr(tx, "outputs", None) or []
        for out in outputs:
            out_addr = getattr(out, "address", None)
            out_value = getattr(out, "value", None)
            if out_addr == address and int(out_value or 0) == amount_sat:
                txid = getattr(tx, "txid", None) or getattr(tx, "hash", None)
                if txid:
                    return txid
    return None


def find_prior_send(
    wallet: "SpendingWallet",
    address: str,
    amount_sat: int,
) -> Optional[str]:
    """Poll bitcoinlib's indexer for up to _RECONCILE_POLL_TIMEOUT_SECONDS for a matching outbound tx.

    A just-broadcast tx may not be visible to the indexer for seconds-to-minutes;
    a single scan that misses it would cause a double-broadcast. None means we
    polled to timeout and still saw nothing — caller must treat as "unknown"
    (do NOT re-broadcast blindly).
    """
    start = time.time()
    while True:
        txid = scan_for_prior_send(wallet, address, amount_sat)
        if txid:
            return txid
        if time.time() - start >= _RECONCILE_POLL_TIMEOUT_SECONDS:
            return None
        time.sleep(_RECONCILE_POLL_INTERVAL_SECONDS)


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

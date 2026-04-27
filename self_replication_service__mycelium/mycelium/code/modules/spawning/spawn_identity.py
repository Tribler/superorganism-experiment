"""Prepares child identity before VPS provisioning: SSH keypair, BTC wallet, SporeStack token + funding.

Every irreversible external call is bracketed by a write-ahead intent record
and a post-success result record. On resume, if an intent exists but no
matching result, we reconcile against the external system (SporeStack balance)
before retrying. This closes the window where a crash between
`wallet.send` returning and us persisting the txid would cause a second
invoice payment, orphaning the first funded SporeStack token.
"""

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Optional

from bitcoinlib.mnemonic import Mnemonic
from bitcoinlib.wallets import Wallet, wallet_delete

from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..core.wallet import SpendingWallet, find_prior_send, get_wallet, parse_bitcoin_uri
from ..monitoring import sporestack_client
from ..monitoring.node_monitor import NodeState
from .errors import SpawnError
from .ssh_deployer import generate_ssh_keypair

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)

_SS_MIN_INVOICE_DOLLARS = 5
_POLL_INTERVAL = 30
_POLL_TIMEOUT = 1800

# Treat an invoice as expired this many seconds before its stated expiry, so we
# don't broadcast against an address that goes dead while our tx is in flight.
_INVOICE_EXPIRY_SAFETY_MARGIN_SECONDS = 60
# Fallback expiry when SporeStack's response omits `expires` (~10 min nominal).
_INVOICE_DEFAULT_LIFETIME_SECONDS = 600
# Conservative upper-bound on bitcoinlib's tx fee, used as a parent-balance
# headroom check so wallet.send doesn't fail with insufficient-for-fee after
# the gate passes.
_ESTIMATED_FEE_SAT_MAX = 5_000
# Runaway-guard: cap the number of fresh invoices minted within a single spawn.
_MAX_FUNDING_ATTEMPTS = 5


@dataclass
class ChildIdentity:
    spawn_id: str               # local spawn ID (passed in)
    sporestack_token: str       # fresh SporeStack API token
    ssh_private_key_path: str   # absolute path to id_ed25519
    ssh_public_key: str         # full content of id_ed25519.pub
    btc_mnemonic: str           # child's BIP39 seed
    btc_address: str            # child's segwit receiving address
    funded_cents: int           # SporeStack balance observed after funding lands


def _generate_child_btc_wallet(spawn_id: str):
    """Create throwaway bitcoinlib wallet in isolated DB; return (mnemonic, address). DB deleted in finally."""
    spawn_dir = Config.DATA_DIR / "spawn" / spawn_id
    spawn_dir.mkdir(parents=True, exist_ok=True)
    temp_db_path = spawn_dir / "child-wallet.db"
    db_uri = f"sqlite:///{temp_db_path}"
    wallet_name = f"child-{spawn_id}"

    mnemonic = Mnemonic().generate()
    try:
        w = Wallet.create(
            wallet_name,
            keys=mnemonic,
            network=Config.BITCOIN_NETWORK,
            db_uri=db_uri,
            witness_type="segwit",
        )
        address = w.get_key().address
        return mnemonic, address
    finally:
        try:
            wallet_delete(wallet_name, db_uri=db_uri, force=True)
        except Exception as e:
            logger.warning("Temp child wallet delete failed: %s", e)
        try:
            temp_db_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Temp child wallet DB unlink failed: %s", e)


async def _wait_for_credit(sporestack_token: str) -> int:
    """Poll /token/{t}/balance every _POLL_INTERVAL s until cents>0 or timeout."""
    start = time.time()
    while time.time() - start < _POLL_TIMEOUT:
        balance = await asyncio.to_thread(sporestack_client.get_balance, sporestack_token)
        if balance:
            cents = int(balance.get("cents", 0))
            if cents > 0:
                elapsed = int(time.time() - start)
                logger.info(
                    "SporeStack credit landed after %ds: %d cents",
                    elapsed, cents,
                )
                return cents
        elapsed = int(time.time() - start)
        logger.info("Waiting for credit... (%ds elapsed)", elapsed)
        await asyncio.sleep(_POLL_INTERVAL)
    raise SpawnError(
        "identity",
        f"Timeout ({_POLL_TIMEOUT}s) waiting for SporeStack credit to land",
    )


def _rehydrate_child_wallet(ps, spawn_id: str):
    """If a matching child-wallet blob was persisted, return (mnemonic, address); else None."""
    blob = ps.get("spawn_child_wallet")
    if not blob or blob.get("spawn_id") != spawn_id:
        return None
    mnemonic = blob.get("btc_mnemonic")
    address = blob.get("btc_address")
    if not mnemonic or not address:
        return None
    return mnemonic, address


def _rehydrate_sporestack_token(ps, spawn_id: str) -> Optional[str]:
    blob = ps.get("spawn_sporestack_token")
    if not blob or blob.get("spawn_id") != spawn_id:
        return None
    return blob.get("sporestack_token") or None


def _intent_is_live(intent: dict) -> bool:
    """An invoice intent is live if its expires timestamp (or fallback) is in the future."""
    expires = intent.get("expires")
    if expires is None:
        created = intent.get("created")
        if created is None:
            return False
        expires = int(created) + _INVOICE_DEFAULT_LIFETIME_SECONDS
    return time.time() < int(expires) - _INVOICE_EXPIRY_SAFETY_MARGIN_SECONDS


async def _mint_funding_invoice(
    ps,
    spawn_id: str,
    sporestack_token: str,
) -> dict:
    """Create a fresh SporeStack invoice and write spawn_funding_intent. Returns the intent dict."""
    attempts = int(ps.get("spawn_funding_attempts", 0))
    if attempts >= _MAX_FUNDING_ATTEMPTS:
        raise SpawnError(
            "identity",
            f"Max funding attempts ({_MAX_FUNDING_ATTEMPTS}) reached for spawn_id={spawn_id}",
        )
    ps.set("spawn_funding_attempts", attempts + 1)

    monthly_cents = sporestack_client.calculate_monthly_vps_cost(
        Config.VPS_FLAVOR, Config.VPS_PROVIDER
    )
    needed_cents = int(monthly_cents * Config.TOPUP_TARGET_DAYS / 30)
    needed_dollars = max(_SS_MIN_INVOICE_DOLLARS, math.ceil(needed_cents / 100))
    logger.info(
        "Funding (attempt %d/%d): monthly=%d cents, target_days=%d → $%d",
        attempts + 1, _MAX_FUNDING_ATTEMPTS, monthly_cents, Config.TOPUP_TARGET_DAYS, needed_dollars,
    )

    response = await asyncio.to_thread(
        sporestack_client.create_invoice, sporestack_token, needed_dollars
    )
    if not response:
        raise SpawnError("identity", "create_invoice returned None")
    invoice = response.get("invoice", response)
    payment_uri = invoice.get("payment_uri", "")
    parsed = parse_bitcoin_uri(payment_uri)
    if not parsed:
        raise SpawnError("identity", f"Cannot parse payment URI: {response!r}")
    pay_address, amount_sat = parsed

    intent = {
        "spawn_id": spawn_id,
        "sporestack_token": sporestack_token,
        "pay_address": pay_address,
        "amount_sat": amount_sat,
        "created": invoice.get("created"),
        "expires": invoice.get("expires"),
    }
    ps.set("spawn_funding_intent", intent)
    logger.info(
        "Invoice: send %d sat to %s (for $%d, expires=%s)",
        amount_sat, pay_address, needed_dollars, intent["expires"],
    )
    return intent


async def _check_parent_balance(wallet: SpendingWallet, amount_sat: int) -> None:
    """Raise SpawnError if parent doesn't have amount_sat plus a fee buffer."""
    wallet_sat = await asyncio.to_thread(wallet.get_balance_satoshis)
    needed = amount_sat + _ESTIMATED_FEE_SAT_MAX
    if wallet_sat < needed:
        raise SpawnError(
            "identity",
            f"Insufficient parent BTC: have {wallet_sat} sat, need {amount_sat} sat "
            f"+ {_ESTIMATED_FEE_SAT_MAX} sat fee buffer ({needed} sat total)",
        )


async def _fund_sporestack_token(
    ps,
    spawn_id: str,
    sporestack_token: str,
    wallet: SpendingWallet,
) -> None:
    """Fund the SporeStack token idempotently under crash.

    Resume modes:
      A. spawn_funding_txid persisted → broadcast already happened, nothing to do.
      B. spawn_funding_intent persisted but no txid → reconcile via get_balance;
         if cents>0, mark reconciled. Else if intent is still live, retry
         wallet.send against the persisted address; if expired, mint a fresh
         invoice (overwriting the intent) before broadcasting.
      C. Nothing persisted → fresh funding: mint invoice, balance check, broadcast.
    """
    existing_txid = ps.get("spawn_funding_txid")
    if existing_txid:
        logger.info(
            "Resume: spawn_funding_txid already persisted (%s) — skipping broadcast",
            existing_txid,
        )
        return

    intent = ps.get("spawn_funding_intent")
    if intent and intent.get("spawn_id") == spawn_id and intent.get("sporestack_token") == sporestack_token:
        logger.info(
            "Resume: spawn_funding_intent found — checking parent wallet history before SporeStack reconcile",
        )
        # Check parent wallet history first: if the prior broadcast committed
        # locally, SporeStack's get_balance may still report 0 cents for 10–60
        # min while the tx confirms in mempool. Re-broadcasting in that window
        # would double-fund the token from a different UTXO set.
        prior_txid = await asyncio.to_thread(
            find_prior_send,
            wallet,
            intent["pay_address"],
            int(intent["amount_sat"]),
        )
        if prior_txid:
            logger.info(
                "Resume: parent wallet shows matching outbound tx %s — treating prior broadcast as committed",
                prior_txid,
            )
            ps.set("spawn_funding_txid", prior_txid)
            return
        balance = await asyncio.to_thread(sporestack_client.get_balance, sporestack_token)
        if balance and int(balance.get("cents", 0)) > 0:
            logger.info(
                "Resume: SporeStack reports %d cents — treating prior broadcast as confirmed",
                int(balance.get("cents", 0)),
            )
            ps.set("spawn_funding_txid", f"reconciled-from-balance-{int(time.time())}")
            return
        if not _intent_is_live(intent):
            logger.warning(
                "Resume: prior invoice expired (created=%s, expires=%s) — minting fresh invoice "
                "before retry to avoid sending to a dead address",
                intent.get("created"), intent.get("expires"),
            )
            intent = await _mint_funding_invoice(ps, spawn_id, sporestack_token)
        pay_address = intent["pay_address"]
        amount_sat = int(intent["amount_sat"])
        logger.info(
            "Resume: retrying wallet.send — %d sat to %s",
            amount_sat, pay_address,
        )
        await _check_parent_balance(wallet, amount_sat)
        # Re-check liveness right before broadcast — invoice could have crossed
        # the safety margin while we were balance-checking.
        if not _intent_is_live(intent):
            raise SpawnError(
                "identity",
                "Invoice expired between balance-check and broadcast on retry; "
                "next attempt will mint a fresh one",
            )
        try:
            txid = await asyncio.to_thread(wallet.send, pay_address, amount_sat)
        except Exception as e:
            raise SpawnError("identity", f"Invoice payment retry failed: {e}") from e
        ps.set("spawn_funding_txid", txid)
        logger.info("Retry broadcast succeeded — txid %s", txid)
        return

    intent = await _mint_funding_invoice(ps, spawn_id, sporestack_token)
    pay_address = intent["pay_address"]
    amount_sat = int(intent["amount_sat"])

    await _check_parent_balance(wallet, amount_sat)
    if not _intent_is_live(intent):
        raise SpawnError(
            "identity",
            "Invoice expired between creation and broadcast; next attempt will mint a fresh one",
        )

    try:
        txid = await asyncio.to_thread(wallet.send, pay_address, amount_sat)
    except Exception as e:
        raise SpawnError("identity", f"Invoice payment failed: {e}") from e
    ps.set("spawn_funding_txid", txid)
    logger.info("Paid invoice — txid %s", txid)


async def prepare_child_identity(
    spawn_id: str,
    node_state: NodeState,
) -> ChildIdentity:
    """Produce SSH keypair, BTC wallet, SporeStack token, and fund it from the parent's wallet.

    Each durable sub-step checks for pre-existing state before calling externally
    and writes state immediately after the external call returns, so that any
    single crash leaves at most a reconcilable intent record behind.
    """
    logger.info("Preparing identity for %s", spawn_id)

    ps = state_module.get()
    if ps is None:
        raise SpawnError("identity", "persistent state not initialised")

    # 1) SSH keypair — regenerating overwrites harmlessly; file on disk is the checkpoint.
    key_path = Config.DATA_DIR / "spawn" / spawn_id / "ssh" / "id_ed25519"
    try:
        priv_key_path, pub_key = generate_ssh_keypair(
            str(key_path),
            key_type="ed25519",
            comment=f"mycelium-{spawn_id}",
        )
    except Exception as e:
        raise SpawnError("identity", f"SSH keypair generation failed: {e}") from e
    logger.info("SSH keypair ready at %s", priv_key_path)

    # 2) Child BTC wallet — persist mnemonic the instant it exists. Losing the
    #    mnemonic strands any inheritance already sent on a retry.
    rehydrated = _rehydrate_child_wallet(ps, spawn_id)
    if rehydrated is not None:
        btc_mnemonic, btc_address = rehydrated
        logger.info("Reusing persisted child BTC wallet: %s", btc_address)
    else:
        try:
            btc_mnemonic, btc_address = _generate_child_btc_wallet(spawn_id)
        except Exception as e:
            raise SpawnError("identity", f"Child BTC wallet generation failed: {e}") from e
        ps.set("spawn_child_wallet", {
            "spawn_id": spawn_id,
            "btc_mnemonic": btc_mnemonic,
            "btc_address": btc_address,
        })
        logger.info("Child BTC address: %s", btc_address)

    # 3) SporeStack token — persist the instant it exists, so any later crash
    #    does not lead to minting a second (unfunded) token on retry.
    sporestack_token = _rehydrate_sporestack_token(ps, spawn_id)
    if sporestack_token:
        logger.info("Reusing persisted SporeStack token")
    else:
        sporestack_token = await asyncio.to_thread(sporestack_client.generate_token)
        if not sporestack_token:
            raise SpawnError("identity", "generate_token returned None")
        ps.set("spawn_sporestack_token", {
            "spawn_id": spawn_id,
            "sporestack_token": sporestack_token,
        })
        logger.info("Minted SporeStack token")

    # 4) Fund the token.
    wallet = get_wallet()
    if wallet is None:
        raise SpawnError("identity", "Parent wallet not initialized")
    await _fund_sporestack_token(ps, spawn_id, sporestack_token, wallet)

    # 5) Poll for credit landing. This is already idempotent — it just reads
    #    `get_balance` until cents > 0.
    funded_cents = await _wait_for_credit(sporestack_token)

    return ChildIdentity(
        spawn_id=spawn_id,
        sporestack_token=sporestack_token,
        ssh_private_key_path=priv_key_path,
        ssh_public_key=pub_key,
        btc_mnemonic=btc_mnemonic,
        btc_address=btc_address,
        funded_cents=funded_cents,
    )

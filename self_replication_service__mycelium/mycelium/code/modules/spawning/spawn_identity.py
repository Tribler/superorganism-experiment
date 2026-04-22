"""
Child identity prep for the spawn pipeline (TODO 10.3).

Produces everything a fresh child needs before we provision a VPS:
  - per-spawn Ed25519 SSH keypair (public key baked into the VPS at launch)
  - fresh BTC wallet (mnemonic for the child, address for the parent's inheritance)
  - fresh SporeStack token (the child's API credential)
  - ~TOPUP_TARGET_DAYS of runway paid onto that token from the parent's wallet

On any failure, raises SpawnIdentityError; deployer.spawn_child catches it and
leaves spawn_in_progress=True so the whole spawn retries from scratch on restart.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass

from bitcoinlib.mnemonic import Mnemonic
from bitcoinlib.wallets import Wallet, wallet_delete

from config import Config
from ..monitoring import sporestack_client
from ..monitoring.node_monitor import NodeState
from .ssh_deployer import generate_ssh_keypair
from ..core.wallet import get_wallet

logger = logging.getLogger(__name__)

_SS_MIN_INVOICE_DOLLARS = 5
_POLL_INTERVAL = 30
_POLL_TIMEOUT = 1800


class SpawnIdentityError(Exception):
    """Any failure during child identity preparation."""
    pass


@dataclass
class ChildIdentity:
    child_token: str            # local spawn ID (passed in)
    sporestack_token: str       # fresh SporeStack API token
    ssh_private_key_path: str   # absolute path to id_ed25519
    ssh_public_key: str         # full content of id_ed25519.pub
    btc_mnemonic: str           # child's BIP39 seed
    btc_address: str            # child's segwit receiving address
    funded_cents: int           # SporeStack balance observed after funding lands


def _parse_bitcoin_uri(uri: str):
    """Parse bitcoin:ADDRESS?amount=BTC → (address, amount_sat) or None."""
    if not uri.startswith("bitcoin:"):
        return None
    parts = uri[8:].split("?")
    address = parts[0]
    amount_btc = None
    if len(parts) > 1:
        for param in parts[1].split("&"):
            if param.startswith("amount="):
                amount_btc = float(param[7:])
                break
    if not address or amount_btc is None:
        return None
    return address, int(amount_btc * 100_000_000)


def _generate_child_btc_wallet(child_token: str):
    """Create a throwaway bitcoinlib wallet in an isolated DB; return (mnemonic, address).

    The DB is deleted in a finally block so no private-key material survives
    beyond this function — the returned mnemonic is the child's authoritative seed.
    """
    spawn_dir = Config.DATA_DIR / "spawn" / child_token
    spawn_dir.mkdir(parents=True, exist_ok=True)
    temp_db_path = spawn_dir / "child-wallet.db"
    db_uri = f"sqlite:///{temp_db_path}"
    wallet_name = f"child-{child_token}"

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
                    "[SPAWN-IDENTITY] SporeStack credit landed after %ds: %d cents",
                    elapsed, cents,
                )
                return cents
        elapsed = int(time.time() - start)
        logger.info("[SPAWN-IDENTITY] Waiting for credit... (%ds elapsed)", elapsed)
        await asyncio.sleep(_POLL_INTERVAL)
    raise SpawnIdentityError(
        f"Timeout ({_POLL_TIMEOUT}s) waiting for SporeStack credit to land"
    )


async def prepare_child_identity(
    child_token: str,
    node_state: NodeState,
) -> ChildIdentity:
    """
    Produce SSH keypair, BTC wallet, SporeStack token, and fund that token with
    ~TOPUP_TARGET_DAYS of runway from the parent's wallet.

    child_token is the local spawn ID (e.g. "child-a1b2c3d4") already generated
    by decision_loop._tick — NOT a SporeStack token.
    """
    logger.info("[SPAWN-IDENTITY] Preparing identity for %s", child_token)

    # 1) SSH keypair
    key_path = Config.DATA_DIR / "spawn" / child_token / "ssh" / "id_ed25519"
    try:
        priv_key_path, pub_key = generate_ssh_keypair(
            str(key_path),
            key_type="ed25519",
            comment=f"mycelium-{child_token}",
        )
    except Exception as e:
        raise SpawnIdentityError(f"SSH keypair generation failed: {e}") from e
    logger.info("[SPAWN-IDENTITY] SSH keypair ready at %s", priv_key_path)

    # 2) BTC wallet (temp, isolated — mnemonic + address are the only survivors)
    try:
        btc_mnemonic, btc_address = _generate_child_btc_wallet(child_token)
    except Exception as e:
        raise SpawnIdentityError(f"Child BTC wallet generation failed: {e}") from e
    logger.info("[SPAWN-IDENTITY] Child BTC address: %s", btc_address)

    # 3) SporeStack token
    sporestack_token = await asyncio.to_thread(sporestack_client.generate_token)
    if not sporestack_token:
        raise SpawnIdentityError("generate_token returned None")
    logger.info("[SPAWN-IDENTITY] Minted SporeStack token")

    # 4) Size the funding (~30 days at the current flavor/provider cost)
    monthly_cents = sporestack_client.calculate_monthly_vps_cost(
        Config.VPS_FLAVOR, Config.VPS_PROVIDER
    )
    needed_cents = int(monthly_cents * Config.TOPUP_TARGET_DAYS / 30)
    needed_dollars = max(_SS_MIN_INVOICE_DOLLARS, math.ceil(needed_cents / 100))
    logger.info(
        "[SPAWN-IDENTITY] Funding: monthly=%d cents, target_days=%d → $%d",
        monthly_cents, Config.TOPUP_TARGET_DAYS, needed_dollars,
    )

    # 5) Invoice
    response = await asyncio.to_thread(
        sporestack_client.create_invoice, sporestack_token, needed_dollars
    )
    if not response:
        raise SpawnIdentityError("create_invoice returned None")
    invoice = response.get("invoice", response)
    payment_uri = invoice.get("payment_uri", "")
    parsed = _parse_bitcoin_uri(payment_uri)
    if not parsed:
        raise SpawnIdentityError(f"Cannot parse payment URI: {response!r}")
    pay_address, amount_sat = parsed
    logger.info(
        "[SPAWN-IDENTITY] Invoice: send %d sat to %s (for $%d)",
        amount_sat, pay_address, needed_dollars,
    )

    # 6) Send BTC from parent wallet
    wallet = get_wallet()
    if wallet is None:
        raise SpawnIdentityError("Parent wallet not initialized")
    wallet_sat = await asyncio.to_thread(wallet.get_balance_satoshis)
    if wallet_sat < amount_sat:
        raise SpawnIdentityError(
            f"Insufficient parent BTC: have {wallet_sat} sat, need {amount_sat} sat"
        )
    try:
        txid = await asyncio.to_thread(wallet.send, pay_address, amount_sat)
    except Exception as e:
        raise SpawnIdentityError(f"Invoice payment failed: {e}") from e
    logger.info("[SPAWN-IDENTITY] Paid invoice — txid %s", txid)

    # 7) Poll for credit landing
    funded_cents = await _wait_for_credit(sporestack_token)

    return ChildIdentity(
        child_token=child_token,
        sporestack_token=sporestack_token,
        ssh_private_key_path=priv_key_path,
        ssh_public_key=pub_key,
        btc_mnemonic=btc_mnemonic,
        btc_address=btc_address,
        funded_cents=funded_cents,
    )

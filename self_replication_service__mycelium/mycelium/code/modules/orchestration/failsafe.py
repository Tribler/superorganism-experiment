"""
Failsafe pipeline.

Triggered by the decision loop when runway drops below FAILSAFE_TRIGGER_DAYS.
Selects the most wealthy live peer and transfers the node's BTC balance to it,
then lets the VPS expire naturally.

If no peers are available, falls back to Config.DEFAULT_BTC_ADDRESS (the
operator's local "mycelium" cold wallet, injected at genesis deploy time and
inherited by all child nodes via MYCELIUM_DEFAULT_BTC_ADDRESS env var).
"""

import asyncio
from typing import List, Optional

from ..core import state as state_module
from config import Config
from utils import setup_logger
from ..monitoring.node_monitor import NodeState
from ..monitoring.peer_registry import PeerInfo
from ..core.wallet import get_wallet

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


def select_best_peer(peers: List[PeerInfo]) -> Optional[PeerInfo]:
    """Return the most wealthy peer (highest BTC balance)."""
    if not peers:
        return None
    return max(peers, key=lambda p: p.btc_balance_sat)


async def _sweep_funds(
    node_state: NodeState, target_address: str, fallback_used: bool
) -> None:
    """Blocking sweep wrapped in asyncio.to_thread; handles cold wallet retry on failure."""
    wallet = get_wallet()
    if wallet is None:
        raise RuntimeError("Wallet not initialized — cannot sweep")

    ps = state_module.get()
    actual_address = target_address

    try:
        txid = await asyncio.to_thread(wallet.sweep_all, target_address)
    except Exception as e:
        if not fallback_used and Config.DEFAULT_BTC_ADDRESS:
            logger.warning(
                "Sweep to peer failed (%s) — retrying with cold wallet", e
            )
            actual_address = Config.DEFAULT_BTC_ADDRESS
            txid = await asyncio.to_thread(wallet.sweep_all, Config.DEFAULT_BTC_ADDRESS)
        else:
            logger.critical("Sweep failed and no fallback available: %s", e)
            raise  # leave failsafe_in_progress=True so recovery retries on next restart

    suffix = " (cold wallet)" if (fallback_used or actual_address == Config.DEFAULT_BTC_ADDRESS) else ""
    logger.info(
        "Swept %d sat to %s%s — txid %s",
        node_state.btc_balance_sat, actual_address, suffix, txid,
    )

    if ps is None:
        raise RuntimeError("Persistent state not initialized")
    ps.mark_failsafe_completed()


async def execute_failsafe(node_state: NodeState, peers: List[PeerInfo]) -> None:
    """Transfer this node's BTC balance to the best available peer, with cold wallet fallback."""
    best = select_best_peer(peers)

    if best is not None:
        target_address = best.btc_address
        fallback_used = False
    elif Config.DEFAULT_BTC_ADDRESS:
        target_address = Config.DEFAULT_BTC_ADDRESS
        fallback_used = True
        logger.warning("No live peers — falling back to cold wallet")
    else:
        logger.critical(
            "No peers and no default address configured — funds may be lost on VPS expiry!"
        )
        return

    ps = state_module.get()
    if ps:
        ps.mark_failsafe_started()

    await _sweep_funds(node_state, target_address, fallback_used)

"""Sends inheritance BTC to the child and marks spawn complete in persistent state."""

import asyncio

from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..core import wallet as wallet_module
from ..monitoring.node_monitor import NodeState
from ..orchestration.spawn_thresholds import compute_child_share
from .spawn_identity import ChildIdentity

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


class SpawnTransferError(Exception):
    """Any failure during inheritance BTC transfer."""
    pass


async def transfer_inheritance(
    identity: ChildIdentity,
    node_state: NodeState,
) -> str:
    """Send inheritance BTC to child. Returns txid. Leaves spawn_in_progress=True on failure for retry."""
    ps = state_module.get()
    wallet = wallet_module.get_wallet()
    if ps is None:
        raise SpawnTransferError("NodePersistentState not initialised")
    if wallet is None:
        raise SpawnTransferError("SpendingWallet not initialised")

    child_share_sat = compute_child_share(node_state.btc_balance_sat)
    logger.info(
        "Transferring inheritance: child_token=%s amount=%d sat to=%s",
        identity.child_token, child_share_sat, identity.btc_address,
    )

    try:
        txid = await asyncio.to_thread(
            wallet.send, identity.btc_address, child_share_sat
        )
    except Exception as e:
        raise SpawnTransferError(
            f"Inheritance transfer failed for {identity.child_token}: {e}"
        ) from e

    ps.mark_spawn_completed(success=True, child_btc_address=identity.btc_address)
    logger.info(
        "Spawn complete: child_token=%s txid=%s amount=%d sat",
        identity.child_token, txid, child_share_sat,
    )
    return txid

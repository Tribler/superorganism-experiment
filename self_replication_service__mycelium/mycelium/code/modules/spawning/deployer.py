from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..monitoring.node_monitor import NodeState
from ..orchestration.spawn_thresholds import compute_child_share, mutate_caution_trait

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


async def spawn_child(node_state: NodeState, caution_trait: float, child_token: str) -> None:
    """Provision VPS, deploy mycelium, inject env, and transfer BTC inheritance. (TODO 10.9: wire pipeline)"""
    ps = state_module.get()
    child_caution = mutate_caution_trait(caution_trait)
    child_share_sat = compute_child_share(node_state.btc_balance_sat)

    try:
        logger.info(
            "Would spawn child: token=%s, share=%d sat, caution=%.3f"
            " — not implemented",
            child_token, child_share_sat, child_caution,
        )
        ps.mark_spawn_completed(success=False, child_btc_address="")
    except Exception:
        logger.error("Unexpected error", exc_info=True)

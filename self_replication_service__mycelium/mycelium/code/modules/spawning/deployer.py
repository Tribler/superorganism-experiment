from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..monitoring.node_monitor import NodeState
from ..orchestration.spawn_thresholds import compute_child_share, mutate_caution_trait

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


async def spawn_child(node_state: NodeState, caution_trait: float, child_token: str) -> None:
    """
    Provision a new VPS, deploy mycelium, inject env, and transfer BTC inheritance.

    Caller has already called ps.mark_spawn_started(child_token).
    This function calls mark_spawn_completed() at the end.

    TODO 10: provision VPS via SporeStack, deploy code, inject env vars, transfer BTC.
    """
    ps = state_module.get()
    child_caution = mutate_caution_trait(caution_trait)
    child_share_sat = compute_child_share(node_state.btc_balance_sat)

    try:
        # TODO 10: provision VPS, deploy code, inject env, transfer BTC.
        # When injecting env vars for the child, include:
        #   MYCELIUM_DEFAULT_BTC_ADDRESS = Config.DEFAULT_BTC_ADDRESS
        # (same pattern as MYCELIUM_CAUTION_TRAIT) so the cold wallet fallback
        # propagates to all descendant nodes automatically.
        logger.info(
            "Would spawn child: token=%s, share=%d sat, caution=%.3f"
            " — not implemented",
            child_token, child_share_sat, child_caution,
        )
        ps.mark_spawn_completed(success=False, child_btc_address="")
        # success=False: stub attempt not recorded in spawn_history;
        # will retry on next tick if still eligible
    except Exception:
        logger.error("Unexpected error", exc_info=True)
        # leave flag set — retry on next restart

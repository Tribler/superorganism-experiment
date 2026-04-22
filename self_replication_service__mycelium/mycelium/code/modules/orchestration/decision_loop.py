"""
Periodically evaluates node financial state and decides:
  1. Failsafe      -> runway critically low → execute_failsafe()
  2. Top-up        -> runway below replenish threshold → topup_sporestack()
  3. Spawn         -> runway healthy, eligibility met → spawn_child()
  4. Do nothing    -> exitlog reason from eligibility check
"""

import asyncio
from uuid import uuid4

from ..spawning import deployer
from . import failsafe
from ..monitoring import node_monitor
from ..monitoring import peer_registry
from ..core import state as state_module
from ..core import event_logger
from . import topup
from config import Config
from utils import setup_logger
from .spawn_thresholds import check_spawn_eligibility

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


def _log(event_type: str, data: dict) -> None:
    _log(event_type, data)


async def _wait_for_node_state(timeout: int = 300) -> None:
    """Poll until NodeMonitor has done at least one refresh (last_updated > 0)."""
    monitor = node_monitor.get_monitor()
    if monitor is None:
        logger.warning("NodeMonitor not initialized, skipping wait")
        return

    elapsed = 0
    while elapsed < timeout:
        if monitor.get_state().last_updated > 0:
            return
        await asyncio.sleep(1)
        elapsed += 1

    logger.warning(
        "Timed out waiting for NodeMonitor to complete first refresh (%ds)",
        timeout,
    )


async def _handle_recovery() -> None:
    """On startup, resume any pipeline that was interrupted by a prior restart."""
    ps = state_module.get()
    if ps is None:
        return

    if ps.is_spawn_in_progress():
        logger.warning("Recovery: spawn was in progress")
        await _wait_for_node_state()
        child_token = ps.get("spawn_child_token", "")
        monitor = node_monitor.get_monitor()
        if monitor is None:
            logger.warning("NodeMonitor not available during spawn recovery")
            return
        node_state = monitor.get_state()
        caution_trait = ps.get_caution_trait()
        await deployer.spawn_child(node_state, caution_trait, child_token)

    elif ps.is_failsafe_in_progress():
        logger.warning("Recovery: failsafe was interrupted — retrying")
        await _wait_for_node_state()
        monitor = node_monitor.get_monitor()
        if monitor is None:
            logger.warning("NodeMonitor not available during failsafe recovery")
            return
        node_state = monitor.get_state()
        registry = peer_registry.get_registry()
        live_peers = registry.get_live_peers() if registry else []
        try:
            await failsafe.execute_failsafe(node_state, live_peers)
        except Exception:
            logger.exception("Failsafe recovery attempt failed — will retry on next restart")


async def _tick() -> None:
    """Single decision cycle."""
    ps = state_module.get()
    monitor = node_monitor.get_monitor()
    registry = peer_registry.get_registry()

    if ps is None or monitor is None or registry is None:
        logger.warning("Singletons not ready, skipping tick")
        return

    node_state = monitor.get_state()
    if node_state.last_updated == 0.0:
        logger.warning("NodeMonitor has not completed first refresh, skipping tick")
        return

    if node_state.days_remaining is None:
        logger.warning("days_remaining unknown (SporeStack unreachable), skipping tick")
        return

    caution_trait = ps.get_caution_trait()
    live_peers = registry.get_live_peers()

    # Guard: pipeline already running
    if ps.is_spawn_in_progress():
        logger.warning("Spawn already in progress, skipping tick")
        return

    if ps.is_failsafe_in_progress():
        logger.warning("Failsafe already in progress, skipping tick")
        return

    _log("decision_tick", {
        "days_remaining": node_state.days_remaining,
        "btc_balance_sat": node_state.btc_balance_sat,
        "caution_trait": caution_trait,
        "live_peer_count": len(live_peers),
    })

    # PRIORITY 1 — failsafe
    if node_state.days_remaining < Config.FAILSAFE_TRIGGER_DAYS:
        logger.critical(
            "CRITICAL: runway %d days < failsafe threshold %d days — executing failsafe",
            node_state.days_remaining, Config.FAILSAFE_TRIGGER_DAYS,
        )
        try:
            await failsafe.execute_failsafe(node_state, live_peers)
            _log("decision_complete", {
                "action": "failsafe", "success": True,
                "days_remaining": node_state.days_remaining,
            })
        except Exception as exc:
            logger.exception("Failsafe failed — leaving flag set for recovery on restart")
            _log("decision_complete", {
                "action": "failsafe", "success": False, "error": str(exc),
            })
        return

    # PRIORITY 2 — top up SporeStack balance
    if node_state.days_remaining < Config.TOPUP_TRIGGER_DAYS:
        logger.info(
            "Runway %d days < topup threshold %d days — topping up SporeStack balance",
            node_state.days_remaining, Config.TOPUP_TRIGGER_DAYS,
        )
        try:
            await topup.topup_sporestack(node_state)
            _log("decision_complete", {
                "action": "topup", "success": True,
                "days_remaining": node_state.days_remaining,
            })
        except Exception as exc:
            _log("decision_complete", {
                "action": "topup", "success": False, "error": str(exc),
            })
            raise
        return

    # PRIORITY 3 — spawn
    eligibility = check_spawn_eligibility(node_state, caution_trait)
    if eligibility.eligible:
        child_token = f"child-{uuid4().hex[:8]}"
        logger.info(
            "Spawn eligible — initiating spawn (token=%s, child_share=%d sat)",
            child_token, eligibility.child_share_sat,
        )
        ps.mark_spawn_started(child_token)
        await deployer.spawn_child(node_state, caution_trait, child_token)
        _log("decision_complete", {
            "action": "spawn", "success": True,
            "child_token": child_token,
            "child_share_sat": eligibility.child_share_sat,
        })
        return

    # PRIORITY 4 — do nothing
    logger.info("No action: %s", eligibility.reason)
    _log("decision_complete", {
        "action": "none", "reason": eligibility.reason,
    })


async def run(running_ref) -> None:
    """Entry point called by the Orchestrator."""
    logger.info("Decision loop starting (interval=%ds)", Config.DECISION_INTERVAL)
    await _handle_recovery()

    while running_ref():
        await asyncio.sleep(Config.DECISION_INTERVAL)
        if running_ref():
            await _tick()

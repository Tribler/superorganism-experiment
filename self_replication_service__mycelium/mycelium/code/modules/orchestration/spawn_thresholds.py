"""
Spawn eligibility thresholds and caution trait inheritance.

Three spawn params (SPAWN_THRESHOLD_DAYS, SPAWN_RESERVE_DAYS, INHERITANCE_RATIO) mirror the
mycelium-simulation model. Caution scales thresholds via base * (1 + caution).

Used by:
  - decision loop (TODO 9): check_spawn_eligibility()
  - spawn pipeline (TODO 10): compute_child_share(), mutate_caution_trait()
"""
import random
from dataclasses import dataclass

from config import Config
from utils import setup_logger
from ..monitoring.node_monitor import NodeState

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


@dataclass
class SpawnEligibility:
    eligible: bool
    runway_ok: bool       # days_remaining >= effective spawn threshold
    reserve_ok: bool      # days_remaining >= effective post-spawn reserve
    reason: str
    effective_threshold: int   # days
    effective_reserve: int     # days
    actual_days: int
    child_share_sat: int       # BTC that would go to child


def compute_child_share(btc_balance_sat: int) -> int:
    """BTC to transfer to child: inheritance_ratio fraction of current balance."""
    return int(btc_balance_sat * Config.INHERITANCE_RATIO)


def check_spawn_eligibility(node_state: NodeState, caution_trait: float) -> SpawnEligibility:
    c = max(0.0, min(1.0, caution_trait))
    effective_threshold = int(Config.SPAWN_THRESHOLD_DAYS * (1 + c))
    effective_reserve   = int(Config.SPAWN_RESERVE_DAYS   * (1 + c))

    if node_state.days_remaining is None:
        return SpawnEligibility(
            eligible=False, runway_ok=False, reserve_ok=False,
            reason="days_remaining unknown",
            effective_threshold=effective_threshold,
            effective_reserve=effective_reserve,
            actual_days=0,
            child_share_sat=0,
        )

    runway_ok  = node_state.days_remaining >= effective_threshold
    reserve_ok = node_state.days_remaining >= effective_reserve
    eligible   = runway_ok and reserve_ok

    child_share = compute_child_share(node_state.btc_balance_sat) if eligible else 0

    if eligible:
        reason = f"eligible (child share: {child_share} sat)"
    elif not runway_ok:
        reason = f"insufficient runway: {node_state.days_remaining}d < {effective_threshold}d required"
    else:
        reason = f"below reserve floor: {node_state.days_remaining}d < {effective_reserve}d"

    logger.debug("Spawn eligibility [caution=%.2f]: %s", caution_trait, reason)
    return SpawnEligibility(
        eligible=eligible, runway_ok=runway_ok, reserve_ok=reserve_ok,
        reason=reason,
        effective_threshold=effective_threshold,
        effective_reserve=effective_reserve,
        actual_days=node_state.days_remaining,
        child_share_sat=child_share,
    )


def mutate_caution_trait(parent_trait: float) -> float:
    """
    Produce a slightly mutated child caution trait via Gaussian drift.
    Called by parent at spawn time; result injected as MYCELIUM_CAUTION_TRAIT for child.
    """
    child = parent_trait + random.gauss(0, Config.CAUTION_MUTATION_SIGMA)
    result = max(Config.CAUTION_TRAIT_MIN, min(Config.CAUTION_TRAIT_MAX, child))
    logger.debug("Caution mutation: %.3f -> %.3f (sigma=%.3f)", parent_trait, result, Config.CAUTION_MUTATION_SIGMA)
    return result

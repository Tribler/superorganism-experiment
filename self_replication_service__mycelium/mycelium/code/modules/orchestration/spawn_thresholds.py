"""
Spawn eligibility thresholds and caution trait inheritance.

Three spawn params (SPAWN_THRESHOLD_DAYS, SPAWN_RESERVE_DAYS, INHERITANCE_RATIO)
Caution scales thresholds via base * (1 + caution).

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
    funds_ok: bool        # post-spawn BTC >= effective_threshold days of runway
    reason: str
    effective_threshold: int   # days
    effective_reserve: int     # days
    actual_days: int
    child_share_sat: int       # BTC that would go to child
    post_spawn_btc_sat: int
    required_btc_sat: int


def _vps_cost_sat() -> int:
    """Sat-equivalent of the SporeStack invoice spawn_identity will mint."""
    cents = max(
        Config.SPORESTACK_MIN_INVOICE_DOLLARS * 100,
        int(Config.VPS_MONTHLY_COST_CENTS * Config.TOPUP_TARGET_DAYS / 30),
    )
    return int((cents / 100) / Config.BTC_USD_RATE * 100_000_000)


def _cost_per_day_sat() -> int:
    cents_per_day = Config.VPS_MONTHLY_COST_CENTS / 30
    return int((cents_per_day / 100) / Config.BTC_USD_RATE * 100_000_000)


def compute_child_share(btc_balance_sat: int) -> int:
    """Inheritance: ratio of the parent's BTC AFTER it has paid the child's VPS invoice."""
    transferable = max(0, btc_balance_sat - _vps_cost_sat())
    return int(transferable * Config.INHERITANCE_RATIO)


def check_spawn_eligibility(node_state: NodeState, caution_trait: float) -> SpawnEligibility:
    c = max(0.0, min(1.0, caution_trait))
    effective_threshold = int(Config.SPAWN_THRESHOLD_DAYS * (1 + c))
    effective_reserve   = int(Config.SPAWN_RESERVE_DAYS   * (1 + c))

    if node_state.days_remaining is None:
        return SpawnEligibility(
            eligible=False, runway_ok=False, reserve_ok=False, funds_ok=False,
            reason="days_remaining unknown",
            effective_threshold=effective_threshold,
            effective_reserve=effective_reserve,
            actual_days=0,
            child_share_sat=0,
            post_spawn_btc_sat=0,
            required_btc_sat=0,
        )

    # Spawn guard uses total_runway_days (bought + convertible funds) so spawn fires
    # whenever the node has the FUNDS to support a child, not only when it has
    # pre-paid VPS days. Falls back to bought-runway if total isn't computed yet.
    runway_basis = node_state.total_runway_days if node_state.total_runway_days is not None else node_state.days_remaining

    vps_cost    = _vps_cost_sat()
    fee         = Config.SPAWN_FEE_BUFFER_SAT
    inheritance = compute_child_share(node_state.btc_balance_sat)
    post_spawn  = node_state.btc_balance_sat - vps_cost - inheritance - fee
    cost_per_day = _cost_per_day_sat()
    required    = effective_threshold * cost_per_day

    runway_ok  = runway_basis >= effective_threshold
    reserve_ok = runway_basis >= effective_reserve
    funds_ok   = post_spawn >= required
    eligible   = runway_ok and reserve_ok and funds_ok

    child_share = inheritance if eligible else 0

    if eligible:
        reason = f"eligible (child share: {child_share} sat)"
    elif not runway_ok:
        reason = f"insufficient runway: {runway_basis}d < {effective_threshold}d required (bought: {node_state.days_remaining}d)"
    elif not reserve_ok:
        reason = f"below reserve floor: {runway_basis}d < {effective_reserve}d"
    else:
        post_spawn_days = post_spawn // cost_per_day if cost_per_day > 0 else 0
        reason = (
            f"post-spawn BTC too low: {post_spawn} sat ({post_spawn_days}d) "
            f"< {required} sat ({effective_threshold}d). "
            f"vps={vps_cost}, inheritance={inheritance}, fee={fee}."
        )

    logger.debug("Spawn eligibility [caution=%.2f]: %s", caution_trait, reason)
    return SpawnEligibility(
        eligible=eligible, runway_ok=runway_ok, reserve_ok=reserve_ok, funds_ok=funds_ok,
        reason=reason,
        effective_threshold=effective_threshold,
        effective_reserve=effective_reserve,
        actual_days=runway_basis,
        child_share_sat=child_share,
        post_spawn_btc_sat=post_spawn,
        required_btc_sat=required,
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

"""Seed-sweep harness for rigorous reporting.

Runs `local_experiment.run_local_experiment` `num_seeds` times with seeds
0..num_seeds-1 (override via --seed-start), captures each run's round
history, then plots mean ± 95% CI across seeds.

Output (under logs/seed_sweep_<timestamp>/):
    - per_seed_<seed>.json      raw round_history per run
    - summary.json              per-round mean / std / 95% CI for each metric
    - mean_reward.png           mean per-round reward across all peers/arms
    - cumulative_reward.png     summed reward over time
    - regret.png                oracle_cumulative - cumulative_reward

CIs use the t-distribution with df = num_seeds - 1 (n=10 → t ≈ 2.262).

CLI:
    python seed_sweep.py --dataset istella --rounds 20 --num-seeds 10 \
                         --hotswap-round 5

Each seed runs in the same process sequentially. The `LTRMABCommunity`
class state is reset between runs (it's already reset inside
`run_local_experiment`), but IPv8 instances are stopped at the end of
each call so successive runs don't accumulate sockets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from local_experiment import (  # noqa: E402
    DATASET_ID,
    LOGS_DIR,
    NUM_PEERS,
    NUM_ROUNDS,
    QUERIES_PER_ROUND,
    run_local_experiment,
)


# n=10 → df=9 → 2.262; n=5 → df=4 → 2.776; etc.
# Computed lazily so we don't hard-import scipy at module import time
# (the rest of the project doesn't pull it in).
def _t_critical(n: int, alpha: float = 0.05) -> float:
    if n < 2:
        return float("nan")
    try:
        from scipy.stats import t
        return float(t.ppf(1 - alpha / 2, df=n - 1))
    except ImportError:
        # Fallback: hardcoded table for common n. Good to 4 decimals.
        table = {
            2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776,
            6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306,
            10: 2.262, 15: 2.145, 20: 2.093, 30: 2.045,
        }
        return table.get(n, 1.96)  # large-n → normal approx


@dataclass
class _CaptureState:
    """Minimal dashboard_state stand-in. `run_local_experiment` writes here;
    we read `round_history` and `oracle` after the run completes."""
    communities: list = field(default_factory=list)
    current_round: int = 0
    phase: str = ""
    config: dict = field(default_factory=dict)
    oracle: dict = field(default_factory=dict)
    round_history: list = field(default_factory=list)

    def event(self, *_a, **_k) -> None:
        pass


def _per_round_metrics(history: list[dict]) -> dict[str, list[float]]:
    """Pull plot-ready metrics out of a single run's round_history.

    Returns parallel lists indexed by round: 1..len(history).
    """
    rounds = [int(h["round"]) for h in history]
    cumulative = [float(h["cumulative_reward"]) for h in history]
    oracle_cum = [float(h["oracle_cumulative"]) for h in history]
    # Mean reward = unweighted mean across active arms of arm_mean_reward.
    # This summarises bandit quality at end of round; biased by how many
    # arms are still active, but that's the same bias seed-to-seed so the
    # CI band is meaningful.
    mean_reward = []
    for h in history:
        amr = h.get("arm_mean_reward", {})
        if amr:
            mean_reward.append(float(np.mean(list(amr.values()))))
        else:
            mean_reward.append(0.0)
    regret = [o - c for o, c in zip(oracle_cum, cumulative)]
    return {
        "round": rounds,
        "mean_reward": mean_reward,
        "cumulative_reward": cumulative,
        "oracle_cumulative": oracle_cum,
        "regret": regret,
    }


def _stack_runs(per_seed: list[dict[str, list[float]]], key: str) -> np.ndarray:
    """Stack a metric across runs into shape (num_seeds, num_rounds).

    Truncates to the shortest run so we don't pad missing rounds with zeros
    (which would distort the CI band)."""
    min_len = min(len(run[key]) for run in per_seed)
    return np.array([run[key][:min_len] for run in per_seed])


def _summarise(stack: np.ndarray, n: int) -> dict[str, np.ndarray]:
    """Compute mean / std / 95% CI half-width per round across seeds."""
    mean = stack.mean(axis=0)
    std = stack.std(axis=0, ddof=1) if n > 1 else np.zeros_like(mean)
    sem = std / np.sqrt(n)
    half = _t_critical(n) * sem
    return {"mean": mean, "std": std, "ci_half": half}


def _plot_band(
    ax,
    rounds: np.ndarray,
    summary: dict[str, np.ndarray],
    label: str,
    color: str,
) -> None:
    mean = summary["mean"]
    half = summary["ci_half"]
    ax.plot(rounds, mean, color=color, label=label, linewidth=2)
    ax.fill_between(rounds, mean - half, mean + half, color=color, alpha=0.2)


async def run_sweep(
    dataset_id: str,
    num_peers: int,
    num_rounds: int,
    queries_per_round: int,
    gossip_enabled: bool,
    hotswap_round: int,
    algorithm: str,
    metric: str,
    seeds: list[int],
    output_dir: Path,
) -> dict:
    """Run `run_local_experiment` once per seed, save raw + summary + plots."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[sweep] output dir: {output_dir}")

    per_seed_metrics: list[dict[str, list[float]]] = []
    oracle: dict | None = None

    for seed in seeds:
        print(f"\n{'=' * 70}\n[sweep] SEED {seed}\n{'=' * 70}")
        state = _CaptureState()
        await run_local_experiment(
            dataset_id=dataset_id,
            num_peers=num_peers,
            num_rounds=num_rounds,
            queries_per_round=queries_per_round,
            gossip_enabled=gossip_enabled,
            hotswap_round=hotswap_round,
            algorithm=algorithm,
            metric=metric,
            dashboard_state=state,
            seed=seed,
        )
        if not state.round_history:
            print(f"[sweep] WARN: seed {seed} produced no round history; skipping")
            continue
        if oracle is None:
            oracle = dict(state.oracle)

        # Persist raw history per seed for re-plotting later without re-running.
        (output_dir / f"per_seed_{seed}.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "config": state.config,
                    "oracle": state.oracle,
                    "round_history": list(state.round_history),
                },
                indent=2,
            )
        )
        per_seed_metrics.append(_per_round_metrics(list(state.round_history)))

    if not per_seed_metrics:
        raise RuntimeError("No successful seeds — nothing to summarise.")

    n = len(per_seed_metrics)
    rounds_axis = np.arange(1, min(len(m["round"]) for m in per_seed_metrics) + 1)

    summaries = {
        key: _summarise(_stack_runs(per_seed_metrics, key), n)
        for key in ("mean_reward", "cumulative_reward", "regret")
    }

    # Save numeric summary
    summary_payload = {
        "dataset": dataset_id,
        "num_seeds": n,
        "seeds_used": seeds[:n],
        "rounds": rounds_axis.tolist(),
        "config": {
            "num_peers": num_peers,
            "num_rounds": num_rounds,
            "queries_per_round": queries_per_round,
            "gossip_enabled": gossip_enabled,
            "hotswap_round": hotswap_round,
            "algorithm": algorithm,
            "metric": metric,
        },
        "oracle": oracle,
        "metrics": {
            key: {
                "mean": s["mean"].tolist(),
                "std": s["std"].tolist(),
                "ci_half_95": s["ci_half"].tolist(),
            }
            for key, s in summaries.items()
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2))
    print(f"[sweep] summary written: {output_dir / 'summary.json'}")

    # Plots — import matplotlib lazily so module import stays cheap.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_specs = [
        ("mean_reward",
         f"Per-round mean arm reward ({metric.upper()})",
         "Round", f"Mean {metric.upper()} across active arms",
         "tab:blue", "mean_reward.png"),
        ("cumulative_reward",
         f"Cumulative reward ({metric.upper()}@10)",
         "Round", f"Cumulative {metric.upper()}@10 across all peers",
         "tab:green", "cumulative_reward.png"),
        ("regret",
         f"Cumulative regret vs. oracle ({metric.upper()}@10)",
         "Round", "Oracle cumulative − bandit cumulative",
         "tab:red", "regret.png"),
    ]
    for key, title, xlabel, ylabel, color, fname in plot_specs:
        fig, ax = plt.subplots(figsize=(8, 5))
        _plot_band(ax, rounds_axis, summaries[key], label=f"mean ± 95% CI (n={n})", color=color)
        ax.set_title(f"{title} — {dataset_id}")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(output_dir / fname, dpi=130)
        plt.close(fig)
        print(f"[sweep] wrote {output_dir / fname}")

    return summary_payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run seeded sweeps of the local LTR MAB experiment "
                    "and emit mean ± 95% CI plots."
    )
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--peers", type=int, default=NUM_PEERS)
    parser.add_argument("--rounds", type=int, default=NUM_ROUNDS)
    parser.add_argument("--queries", type=int, default=QUERIES_PER_ROUND)
    parser.add_argument("--no-gossip", action="store_true")
    parser.add_argument("--hotswap-round", type=int, default=0)
    parser.add_argument("--algorithm", choices=["ucb1", "thompson"], default="ucb1")
    parser.add_argument("--metric", choices=["ndcg", "mrr"], default="ndcg")
    parser.add_argument("--num-seeds", type=int, default=10,
                        help="Number of seeds to run (default: 10)")
    parser.add_argument("--seed-start", type=int, default=0,
                        help="First seed value; uses [seed-start, seed-start+num-seeds)")
    parser.add_argument("--output-dir", default=None,
                        help="Override output directory "
                             "(default: logs/seed_sweep_<timestamp>)")
    args = parser.parse_args()

    seeds = list(range(args.seed_start, args.seed_start + args.num_seeds))

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = LOGS_DIR / f"seed_sweep_{ts}"

    asyncio.run(run_sweep(
        dataset_id=args.dataset,
        num_peers=args.peers,
        num_rounds=args.rounds,
        queries_per_round=args.queries,
        gossip_enabled=not args.no_gossip,
        hotswap_round=args.hotswap_round,
        algorithm=args.algorithm,
        metric=args.metric,
        seeds=seeds,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()

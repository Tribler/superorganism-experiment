"""Driver for Experiment 1: Single-Peer Convergence.

Setup (per the thesis): one peer runs Algorithm 1 over the four available
models with no gossip and no model injection. UCB1 vs Thompson Sampling,
100 rounds of 100 queries each, on every available dataset.

Reproducibility (per the thesis): every (dataset, algorithm) configuration
is run with 10 different random seeds; reported values are means with 95%
confidence intervals.

Outputs (in exp1_results/):
  - <dataset>_<algorithm>.json     per-(dataset, algo, seed) raw results
  - aggregated.json                mean / 95% CI over the 10 seeds
  - plots/per_arm/<ds>_<algo>.png|pdf
        per-arm mean-reward trajectories with 95% CI bands
  - plots/cumulative/<ds>.png|pdf
        UCB1 vs Thompson cumulative reward + oracle line
  - plots/regret/<ds>.png|pdf
        cumulative regret = oracle - algo, both algos overlaid
  - plots/pulls/<ds>_<algo>.png|pdf
        final arm-pull distribution averaged across seeds
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import time
from pathlib import Path

import numpy as np

from local_experiment import run_local_experiment
from datasets import detect_datasets


HERE = Path(__file__).parent
OUT_DIR = HERE / "exp1_results"
PLOT_DIR = OUT_DIR / "plots"
DATA_DIR = HERE / "data"

NUM_ROUNDS = 100
QUERIES_PER_ROUND = 100

# 10 fixed seeds, recorded here for reproducibility. Mix of well-known
# constants (Euler, Pi, etc. shifted) so the values are obviously curated
# rather than the system default.
SEEDS = [42, 1337, 2718, 3141, 161803, 271828, 577215, 14142, 86420, 99999]

ALGORITHMS = ["ucb1", "thompson"]


# ---------------------------------------------------------------- run loop

class _Capture:
    """Minimal dashboard stub that records the per-round trace."""
    def __init__(self):
        self.communities = []
        self.current_round = 0
        self.phase = ""
        self.config: dict = {}
        self.oracle: dict = {}
        self.round_history: list = []
    def event(self, *a, **k):
        pass


def _per_arm_history(round_history: list[dict]) -> dict[str, list[float]]:
    """{arm: [mean_reward_round1, ..., mean_reward_roundN]}."""
    arms: set[str] = set()
    for r in round_history:
        arms.update(r.get("arm_mean_reward", {}).keys())
    out: dict[str, list[float]] = {a: [] for a in sorted(arms)}
    for r in round_history:
        snap = r.get("arm_mean_reward", {})
        for a in out:
            out[a].append(float(snap.get(a, 0.0)))
    return out


async def run_one(dataset_id: str, algorithm: str, seed: int) -> dict:
    state = _Capture()
    t0 = time.time()
    # Per-run logs go to logs/experiment_<timestamp>.log; we silence stdout
    # to keep the driver's progress line readable. Errors still propagate
    # via the exception path.
    with contextlib.redirect_stdout(io.StringIO()):
        await run_local_experiment(
            dataset_id=dataset_id,
            num_peers=1,
            num_rounds=NUM_ROUNDS,
            queries_per_round=QUERIES_PER_ROUND,
            gossip_enabled=False,
            hotswap_round=0,
            algorithm=algorithm,
            metric="ndcg",
            dashboard_state=state,
            seed=seed,
        )
    elapsed = time.time() - t0

    if not state.communities:
        raise RuntimeError("no community after run")
    comm = state.communities[0]
    arm_stats = comm.bandit.get_stats()
    cumulative = [r.get("cumulative_reward", 0.0) for r in state.round_history]
    oracle_cumulative = [r.get("oracle_cumulative", 0.0) for r in state.round_history]
    arm_pulls_final = {n: int(s["pulls"]) for n, s in arm_stats.items()}

    return {
        "dataset": dataset_id,
        "algorithm": algorithm,
        "seed": seed,
        "elapsed_seconds": round(elapsed, 1),
        "rounds": NUM_ROUNDS,
        "queries_per_round": QUERIES_PER_ROUND,
        "total_queries": comm.queries_processed,
        "best_arm": comm.bandit.get_best_arm(),
        "oracle": state.oracle,
        "arm_stats": arm_stats,
        "arm_pulls_final": arm_pulls_final,
        "per_arm_mean_reward_history": _per_arm_history(state.round_history),
        "cumulative_reward_history": cumulative,
        "oracle_cumulative_history": oracle_cumulative,
    }


# ---------------------------------------------------------------- aggregation

def _ci95(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (mean, half_width) for the 95% CI of `samples` along axis 0.

    Uses the normal-approximation 1.96 * sigma / sqrt(n). With n = 10 and
    typical bandit reward variance this is the standard convention used in
    LTR / RL papers; t-distribution would be more rigorous but harder to
    explain in a thesis figure caption.
    """
    if samples.shape[0] < 2:
        return samples.mean(axis=0), np.zeros(samples.shape[1:])
    mean = samples.mean(axis=0)
    sem = samples.std(axis=0, ddof=1) / np.sqrt(samples.shape[0])
    return mean, 1.96 * sem


def aggregate_seeds(runs: list[dict]) -> dict:
    """Pool 10 per-seed runs of one (dataset, algorithm) into mean/CI bands."""
    if not runs:
        return {}
    arms = sorted({a for r in runs for a in r["per_arm_mean_reward_history"]})
    n_rounds = max(len(r["cumulative_reward_history"]) for r in runs)

    # Per-arm mean reward trajectory: stack [seeds, rounds] per arm.
    per_arm = {}
    for a in arms:
        rows = []
        for r in runs:
            row = r["per_arm_mean_reward_history"].get(a, [0.0] * n_rounds)
            # Pad if needed (shouldn't happen with fixed NUM_ROUNDS).
            row = row + [row[-1] if row else 0.0] * (n_rounds - len(row))
            rows.append(row)
        arr = np.array(rows, dtype=float)
        mean, hw = _ci95(arr)
        per_arm[a] = {"mean": mean.tolist(), "ci95": hw.tolist()}

    # Cumulative reward and oracle.
    cum = np.array([r["cumulative_reward_history"] for r in runs], dtype=float)
    cum_oracle = np.array([r["oracle_cumulative_history"] for r in runs], dtype=float)
    cum_mean, cum_hw = _ci95(cum)
    oracle_mean, oracle_hw = _ci95(cum_oracle)

    # Final-arm pulls (averaged across seeds).
    pull_arms = sorted({a for r in runs for a in r["arm_pulls_final"]})
    pulls_mat = np.array(
        [[r["arm_pulls_final"].get(a, 0) for a in pull_arms] for r in runs],
        dtype=float,
    )
    pulls_mean, pulls_hw = _ci95(pulls_mat)

    # Best-arm vote.
    from collections import Counter
    best_counter = Counter(r["best_arm"] for r in runs)

    # Oracle leaderboard (averaged across seeds — should be identical, since
    # the oracle is deterministic given the dataset).
    if runs[0].get("oracle"):
        oracle_table = runs[0]["oracle"]
    else:
        oracle_table = {}

    return {
        "n_seeds": len(runs),
        "seeds": [r["seed"] for r in runs],
        "per_arm_mean_reward": per_arm,
        "cumulative_reward": {
            "mean": cum_mean.tolist(),
            "ci95": cum_hw.tolist(),
        },
        "oracle_cumulative": {
            "mean": oracle_mean.tolist(),
            "ci95": oracle_hw.tolist(),
        },
        "arm_pulls_final": {
            "arms": pull_arms,
            "mean": pulls_mean.tolist(),
            "ci95": pulls_hw.tolist(),
        },
        "best_arm_counts": dict(best_counter),
        "oracle_leaderboard": oracle_table,
    }


# ---------------------------------------------------------------- plotting

def _save_both(fig, path_stem: Path) -> None:
    fig.savefig(path_stem.with_suffix(".png"), dpi=160, bbox_inches="tight")
    fig.savefig(path_stem.with_suffix(".pdf"), bbox_inches="tight")


def plot_per_arm(dataset: str, algorithm: str, agg: dict, out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    out_dir.mkdir(parents=True, exist_ok=True)
    per_arm = agg["per_arm_mean_reward"]
    if not per_arm:
        return
    arms = sorted(per_arm.keys())
    rounds = np.arange(1, len(next(iter(per_arm.values()))["mean"]) + 1)
    fig, ax = plt.subplots(figsize=(8, 5))
    for a in arms:
        m = np.array(per_arm[a]["mean"])
        h = np.array(per_arm[a]["ci95"])
        ax.plot(rounds, m, label=a, linewidth=1.5)
        ax.fill_between(rounds, m - h, m + h, alpha=0.18)
    ax.set_xlabel("Round")
    ax.set_ylabel("Mean reward (NDCG@1)")
    ax.set_title(f"Per-arm mean reward — {dataset} / {algorithm}\n"
                 f"mean ± 95% CI over {agg['n_seeds']} seeds")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    _save_both(fig, out_dir / f"{dataset}_{algorithm}")
    plt.close(fig)


def plot_cumulative(dataset: str, agg_by_algo: dict[str, dict], out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    rounds = None
    for algo, agg in agg_by_algo.items():
        m = np.array(agg["cumulative_reward"]["mean"])
        h = np.array(agg["cumulative_reward"]["ci95"])
        rounds = np.arange(1, len(m) + 1)
        ax.plot(rounds, m, label=f"{algo} (cumulative)", linewidth=1.6)
        ax.fill_between(rounds, m - h, m + h, alpha=0.18)
    # Oracle line — same across algorithms, so use any.
    if rounds is not None:
        any_agg = next(iter(agg_by_algo.values()))
        om = np.array(any_agg["oracle_cumulative"]["mean"])
        ax.plot(rounds, om, "--", color="black", label="oracle", linewidth=1.2)
    ax.set_xlabel("Round")
    ax.set_ylabel("Cumulative reward (NDCG@10 sum)")
    ax.set_title(f"Cumulative reward vs oracle — {dataset}")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    _save_both(fig, out_dir / dataset)
    plt.close(fig)


def plot_regret(dataset: str, agg_by_algo: dict[str, dict], out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo, agg in agg_by_algo.items():
        m = np.array(agg["cumulative_reward"]["mean"])
        h = np.array(agg["cumulative_reward"]["ci95"])
        om = np.array(agg["oracle_cumulative"]["mean"])
        regret = om - m
        rounds = np.arange(1, len(regret) + 1)
        ax.plot(rounds, regret, label=algo, linewidth=1.6)
        # CI is symmetric around algo's cumulative; regret CI is the same width.
        ax.fill_between(rounds, regret - h, regret + h, alpha=0.18)
    ax.set_xlabel("Round")
    ax.set_ylabel("Cumulative regret (oracle − algo)")
    ax.set_title(f"Cumulative regret — {dataset}")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    _save_both(fig, out_dir / dataset)
    plt.close(fig)


def plot_pulls(dataset: str, algorithm: str, agg: dict, out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    out_dir.mkdir(parents=True, exist_ok=True)
    pulls = agg["arm_pulls_final"]
    arms = pulls["arms"]
    means = np.array(pulls["mean"])
    hws = np.array(pulls["ci95"])
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(arms))
    ax.bar(x, means, yerr=hws, capsize=4, color="steelblue", edgecolor="black", linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(arms, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Final pulls (avg ± 95% CI)")
    ax.set_title(f"Final arm-pull distribution — {dataset} / {algorithm}")
    ax.grid(True, axis="y", alpha=0.3)
    _save_both(fig, out_dir / f"{dataset}_{algorithm}")
    plt.close(fig)


# ---------------------------------------------------------------- main

async def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    PLOT_DIR.mkdir(exist_ok=True)
    datasets = detect_datasets(DATA_DIR)
    if not datasets:
        print("No datasets detected under data/. Aborting.")
        return

    print(f"Datasets:    {datasets}")
    print(f"Algorithms:  {ALGORITHMS}")
    print(f"Seeds:       {SEEDS}")
    total = len(datasets) * len(ALGORITHMS) * len(SEEDS)
    print(f"Total runs:  {total}")
    print()

    # Per-(dataset, algorithm) → list of per-seed result dicts.
    bucketed: dict[tuple[str, str], list[dict]] = {}
    counter = 0
    overall_t0 = time.time()
    for ds in datasets:
        for algo in ALGORITHMS:
            for seed in SEEDS:
                counter += 1
                tag = f"[{counter:>3}/{total}] {ds:<14} {algo:<8} seed={seed}"
                print(f"{tag} ... ", end="", flush=True)
                t0 = time.time()
                r = await run_one(ds, algo, seed)
                bucketed.setdefault((ds, algo), []).append(r)
                print(f"done in {time.time() - t0:5.1f}s "
                      f"(best={r['best_arm']})")
    print(f"\nAll {total} runs finished in {(time.time() - overall_t0) / 60:.1f} min")

    # Persist raw + aggregated.
    aggregated = {}
    for (ds, algo), runs in bucketed.items():
        out_path = OUT_DIR / f"{ds}_{algo}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"runs": runs}, f, indent=2)
        agg = aggregate_seeds(runs)
        aggregated[f"{ds}/{algo}"] = agg

    with open(OUT_DIR / "aggregated.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "seeds": SEEDS,
                "rounds": NUM_ROUNDS,
                "queries_per_round": QUERIES_PER_ROUND,
                "datasets": datasets,
                "algorithms": ALGORITHMS,
                "by_config": aggregated,
            },
            f,
            indent=2,
        )

    # Plots.
    print("\nGenerating plots...")
    per_arm_dir = PLOT_DIR / "per_arm"
    cumulative_dir = PLOT_DIR / "cumulative"
    regret_dir = PLOT_DIR / "regret"
    pulls_dir = PLOT_DIR / "pulls"
    for ds in datasets:
        agg_by_algo = {algo: aggregated[f"{ds}/{algo}"] for algo in ALGORITHMS}
        plot_cumulative(ds, agg_by_algo, cumulative_dir)
        plot_regret(ds, agg_by_algo, regret_dir)
        for algo in ALGORITHMS:
            agg = aggregated[f"{ds}/{algo}"]
            plot_per_arm(ds, algo, agg, per_arm_dir)
            plot_pulls(ds, algo, agg, pulls_dir)
    print(f"Plots saved under {PLOT_DIR}/")

    # Console summary.
    print("\n" + "=" * 78)
    print(f"{'Dataset':<14} {'Algo':<10} {'Best (mode)':<32} {'Oracle leader':<22}")
    print("=" * 78)
    for ds in datasets:
        for algo in ALGORITHMS:
            agg = aggregated[f"{ds}/{algo}"]
            counts = agg["best_arm_counts"]
            best_mode = max(counts, key=counts.get)
            best_share = f"{best_mode} ({counts[best_mode]}/{agg['n_seeds']})"
            oracle = agg.get("oracle_leaderboard", {})
            oracle_leader = max(oracle, key=oracle.get) if oracle else "?"
            print(f"{ds:<14} {algo:<10} {best_share:<32} {oracle_leader:<22}")


if __name__ == "__main__":
    asyncio.run(main())

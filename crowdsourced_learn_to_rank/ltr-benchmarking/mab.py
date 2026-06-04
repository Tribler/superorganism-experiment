"""Multi-Armed Bandit for ranking model selection.

Each peer maintains its own per-arm pull/reward statistics from its own actions
plus a small table of the latest gossiped statistics from other peers, keyed by
sender peer-id and gated by a Lamport stamp. There is no CRDT merge: gossiped
observations replace prior observations from the same sender when a higher
Lamport tick arrives.

Aggregate statistics for arm selection and elimination are computed as the sum
of own + every known peer-observation. Wall-clock TTL evicts observations from
peers that have gone silent.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import json
from datetime import datetime, timezone


def _derive_rng(seed: int | None, *tags) -> np.random.Generator:
    """Build a per-site deterministic Generator from a master seed + tags.

    When `seed` is None, returns a fresh non-deterministic Generator so the
    non-seeded code path keeps its previous behaviour. When seeded, the tags
    (e.g. peer_id, purpose) namespace the stream so distinct call sites don't
    share draws — critical because a single master seed is reused across
    every RNG in the experiment.
    """
    if seed is None:
        return np.random.default_rng()

    spawn_key = tuple(abs(hash(t)) % (2**32) for t in tags)
    ss = np.random.SeedSequence(entropy=seed, spawn_key=spawn_key)
    return np.random.default_rng(ss)


class RankingModel(Protocol):
    def predict(self, X: np.ndarray) -> np.ndarray: ...


@dataclass
class PeerObservation:
    """Latest gossiped statistics from one other peer for one arm.

    Replaced wholesale when a higher-Lamport message arrives from the same
    sender. Wall-clock `last_received` drives TTL eviction of silent peers.
    """
    pulls: int = 0
    total_reward: float = 0.0
    alpha: float = 1.0
    beta: float = 1.0
    lamport: int = 0
    last_received: float = 0.0  # wall-clock seconds


@dataclass
class ArmStats:
    """Aggregated statistics for a single arm (model)."""
    name: str
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls > 0 else 0.0


# How long to keep a peer's observations after their last gossip arrived.
# Beyond this, the entry is treated as stale and dropped from aggregation.
PEER_OBSERVATION_TTL_S = 300.0


class _BanditBase:
    """Common state shared by UCB1 and ThompsonSampling.

    Each subclass owns the algorithm-specific aggregation and selection rules,
    but share the gossip plumbing: per-arm own-stats + a (sender → observation)
    table per arm, gated by Lamport stamps and wall-clock TTL.
    """

    def __init__(self, arm_names: list[str], peer_id: str = "local"):
        self.peer_id = peer_id
        # Own per-arm evidence accumulated from this peer's own pulls.
        self.own: dict[str, PeerObservation] = {
            name: PeerObservation(alpha=1.0, beta=1.0) for name in arm_names
        }
        # Per-arm table of the latest observation from every other peer.
        # Keyed by sender peer-id; replaced when a higher Lamport arrives.
        self.peer_observations: dict[str, dict[str, PeerObservation]] = {
            name: {} for name in arm_names
        }
        # Per-(sender, arm) Lamport hi-water mark used to gate updates.
        self._lamport_seen: dict[tuple[str, str], int] = {}
        # Local Lamport counter, bumped on every own update so we always
        # broadcast a strictly increasing stamp for our own observations.
        self._lamport_self: int = 0

    @property
    def tables(self) -> dict[str, dict[str, PeerObservation]]:
        """Compatibility shim for callers that used the old `tables` dict.

        The new shape is {arm: {sender_or_self: PeerObservation}}; this view
        composes own + peer_observations on the fly.
        """
        result: dict[str, dict[str, PeerObservation]] = {}
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        for name, own_obs in self.own.items():
            entries: dict[str, PeerObservation] = {self.peer_id: own_obs}
            for sender, obs in self.peer_observations.get(name, {}).items():
                if obs.last_received >= cutoff:
                    entries[sender] = obs
            result[name] = entries
        return result

    def _all_arms(self) -> list[str]:
        return list(self.own.keys())

    def _evict_stale(self, arm: str) -> None:
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        table = self.peer_observations.get(arm, {})
        for sender in [s for s, obs in table.items() if obs.last_received < cutoff]:
            del table[sender]

    @property
    def total_pulls(self) -> int:
        """Sum of own + all (non-stale) peer-reported pulls across every arm."""
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        total = sum(o.pulls for o in self.own.values())
        for table in self.peer_observations.values():
            for obs in table.values():
                if obs.last_received >= cutoff:
                    total += obs.pulls
        return total

    def _aggregate_pulls(self, arm: str) -> int:
        """Aggregate pull count for an arm across own + fresh peer observations."""
        if arm not in self.own:
            return 0
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        n = self.own[arm].pulls
        for obs in self.peer_observations.get(arm, {}).values():
            if obs.last_received >= cutoff:
                n += obs.pulls
        return n

    def add_arm(self, name: str) -> None:
        """Register a new arm with a flat prior."""
        if name in self.own:
            return
        self.own[name] = PeerObservation(alpha=1.0, beta=1.0)
        self.peer_observations.setdefault(name, {})

    def apply_gossip(
        self,
        arm: str,
        sender: str,
        pulls: int,
        total_reward: float,
        alpha: float,
        beta: float,
        lamport: int,
    ) -> bool:
        """Integrate one peer's gossiped observation; returns True if accepted."""
        if sender == self.peer_id:
            return False  # don't echo our own evidence back into the table
        key = (sender, arm)
        if lamport <= self._lamport_seen.get(key, 0):
            return False
        self._lamport_seen[key] = lamport
        self.peer_observations.setdefault(arm, {})[sender] = PeerObservation(
            pulls=pulls,
            total_reward=total_reward,
            alpha=alpha,
            beta=beta,
            lamport=lamport,
            last_received=time.time(),
        )
        return True

    def next_lamport(self) -> int:
        """Bump and return the local Lamport counter (used by the gossip sender)."""
        self._lamport_self += 1
        return self._lamport_self

    def own_observation(self, arm: str) -> PeerObservation | None:
        return self.own.get(arm)

    def evict_all_stale(self) -> int:
        """Drop expired peer-observation entries for every arm. Returns count."""
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        evicted = 0
        for table in self.peer_observations.values():
            stale = [s for s, obs in table.items() if obs.last_received < cutoff]
            for s in stale:
                del table[s]
                evicted += 1
        return evicted


class UCB1(_BanditBase):
    """Upper Confidence Bound algorithm with gossip-aggregated statistics."""

    def __init__(self, arm_names: list[str], c: float = 2.0, peer_id: str = "local", seed: int | None = None):
        super().__init__(arm_names, peer_id=peer_id)
        self.c = c
        # Dedicated RNG for tiebreaking so ties don't depend on dict order.
        self._rng = _derive_rng(seed, peer_id, "ucb1")

    def _aggregate(self, arm: str) -> tuple[float, int]:
        """Return (total_reward, total_pulls) aggregated across own + peers."""
        if arm not in self.own:
            return 0.0, 0
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        own = self.own[arm]
        R = own.total_reward
        n = own.pulls
        for obs in self.peer_observations.get(arm, {}).values():
            if obs.last_received >= cutoff:
                R += obs.total_reward
                n += obs.pulls
        return R, n

    @property
    def arms(self) -> dict[str, ArmStats]:
        result: dict[str, ArmStats] = {}
        for name in self.own:
            R, n = self._aggregate(name)
            result[name] = ArmStats(name=name, pulls=n, total_reward=R)
        return result

    def select_arm(self, active: set[str] | None = None) -> str:
        """Select arm using UCB1 with log(N+1)/(n+1) formula.

        Iteration is over a sorted candidate list and ties are broken by the
        bandit's dedicated RNG so two runs with the same seed make the same
        choice regardless of set/dict insertion order.
        """
        candidates = sorted(active if active is not None else set(self.own))

        for name in candidates:
            _, n = self._aggregate(name)
            if n == 0:
                return name

        N = self.total_pulls
        best_ucb = -float("inf")
        best_arms: list[str] = []
        for name in candidates:
            R, n = self._aggregate(name)
            exploration = self.c * np.sqrt(np.log(N + 1) / (n + 1))
            ucb = R / n + exploration
            if ucb > best_ucb:
                best_ucb = ucb
                best_arms = [name]
            elif ucb == best_ucb:
                best_arms.append(name)

        if len(best_arms) == 1:
            return best_arms[0]
        return best_arms[int(self._rng.integers(len(best_arms)))]

    def update(self, arm_name: str, reward: float) -> None:
        """Update own observation for the selected arm and bump Lamport."""
        own = self.own[arm_name]
        own.pulls += 1
        own.total_reward += reward
        own.lamport = self.next_lamport()
        own.last_received = time.time()

    def get_best_arm(self) -> str:
        return max(
            self.own,
            key=lambda name: (lambda R, n: R / n if n > 0 else 0.0)(*self._aggregate(name)),
        )

    def confidence_bounds(self, arm: str) -> tuple[float, float]:
        """Return (lcb, ucb) using Hoeffding bound: mean ± sqrt(log(N+1) / (2n))."""
        R, n = self._aggregate(arm)
        if n == 0:
            return 0.0, 1.0
        N = self.total_pulls
        mean = R / n
        half_width = np.sqrt(np.log(N + 1) / (2 * n))
        return max(0.0, mean - half_width), min(1.0, mean + half_width)

    def get_stats(self) -> dict:
        result: dict[str, dict] = {}
        for name in self.own:
            R, n = self._aggregate(name)
            result[name] = {
                "pulls": n,
                "total_reward": R,
                "mean_reward": R / n if n > 0 else 0.0,
            }
        return result


class ThompsonSampling(_BanditBase):
    """Thompson Sampling with gossip-aggregated Beta posteriors."""

    def __init__(self, arm_names: list[str], peer_id: str = "local", seed: int | None = None):
        super().__init__(arm_names, peer_id=peer_id)
        # Dedicated RNG for Beta posterior sampling.
        self._rng = _derive_rng(seed, peer_id, "thompson")

    def _aggregate(self, arm: str) -> tuple[float, float, int]:
        """Return (alpha, beta, pulls) aggregated across own + peers.

        The Beta(1,1) prior is counted once, not once per contributor.
        """
        if arm not in self.own:
            return 1.0, 1.0, 0
        cutoff = time.time() - PEER_OBSERVATION_TTL_S
        own = self.own[arm]
        alpha = 1.0 + (own.alpha - 1.0)
        beta = 1.0 + (own.beta - 1.0)
        n = own.pulls
        for obs in self.peer_observations.get(arm, {}).values():
            if obs.last_received >= cutoff:
                alpha += obs.alpha - 1.0
                beta += obs.beta - 1.0
                n += obs.pulls
        return alpha, beta, n

    @property
    def arms(self) -> dict[str, dict]:
        result = {}
        for name in self.own:
            alpha, beta, n = self._aggregate(name)
            result[name] = {"alpha": alpha, "beta": beta, "pulls": n}
        return result

    def select_arm(self, active: set[str] | None = None) -> str:
        candidates = sorted(active if active is not None else set(self.own))

        for name in candidates:
            _, _, n = self._aggregate(name)
            if n == 0:
                return name

        best_name = candidates[0]
        best_sample = -1.0
        for name in candidates:
            alpha, beta, _ = self._aggregate(name)
            sample = float(self._rng.beta(alpha, beta))
            if sample > best_sample:
                best_sample = sample
                best_name = name

        return best_name

    def update(self, arm_name: str, reward: float) -> None:
        own = self.own[arm_name]
        own.alpha += reward
        own.beta += 1.0 - reward
        own.pulls += 1
        own.lamport = self.next_lamport()
        own.last_received = time.time()

    def get_best_arm(self) -> str:
        return max(
            self.own,
            key=lambda name: (lambda a, b, _: a / (a + b))(*self._aggregate(name)),
        )

    def confidence_bounds(self, arm: str) -> tuple[float, float]:
        alpha, beta, n = self._aggregate(arm)
        if n == 0:
            return 0.0, 1.0
        N = self.total_pulls
        mean = alpha / (alpha + beta)
        half_width = np.sqrt(np.log(N + 1) / (2 * n))
        return max(0.0, mean - half_width), min(1.0, mean + half_width)

    def get_stats(self) -> dict:
        result = {}
        for name in self.own:
            alpha, beta, n = self._aggregate(name)
            result[name] = {
                "pulls": n,
                "alpha": alpha,
                "beta": beta,
                "expected_reward": alpha / (alpha + beta),
            }
        return result


@dataclass
class SimulationResult:
    """Results from a MAB simulation."""
    algorithm: str
    total_rounds: int
    cumulative_reward: float
    cumulative_regret: float
    arm_stats: dict
    reward_history: list[float] = field(default_factory=list)
    regret_history: list[float] = field(default_factory=list)
    selection_history: list[str] = field(default_factory=list)

    def save(self, path: Path | str):
        path = Path(path)
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "algorithm": self.algorithm,
            "total_rounds": self.total_rounds,
            "cumulative_reward": self.cumulative_reward,
            "cumulative_regret": self.cumulative_regret,
            "arm_stats": self.arm_stats,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


class ModelBandit:
    """MAB wrapper for ranking models."""

    def __init__(
        self,
        models: dict[str, RankingModel],
        algorithm: str = "ucb1",
        c: float = 2.0,
        peer_id: str = "local",
    ):
        self.models = models
        arm_names = list(models.keys())

        if algorithm == "ucb1":
            self.bandit = UCB1(arm_names, c=c, peer_id=peer_id)
        elif algorithm == "thompson":
            self.bandit = ThompsonSampling(arm_names, peer_id=peer_id)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        self.algorithm = algorithm

    def select_and_rank(self, X: np.ndarray) -> tuple[str, np.ndarray]:
        arm = self.bandit.select_arm()
        scores = self.models[arm].predict(X)
        return arm, scores

    def update(self, arm: str, reward: float):
        self.bandit.update(arm, reward)

    def get_stats(self) -> dict:
        return self.bandit.get_stats()


def simulate_bandit(
    models: dict[str, RankingModel],
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    algorithm: str = "ucb1",
    c: float = 2.0,
) -> SimulationResult:
    """Single-peer simulation kept for benchmark.py compatibility."""
    bandit = ModelBandit(models, algorithm=algorithm, c=c)

    model_scores = {name: model.predict(X) for name, model in models.items()}

    query_rewards = {name: [] for name in models}
    start_idx = 0
    for group_size in groups:
        end_idx = start_idx + group_size
        y_q = y[start_idx:end_idx]

        for name in models:
            scores_q = model_scores[name][start_idx:end_idx]
            top_idx = np.argmax(scores_q)
            reward = 1.0 if y_q[top_idx] > 0 else 0.0
            query_rewards[name].append(reward)

        start_idx = end_idx

    n_queries = len(groups)
    optimal_rewards = [max(query_rewards[name][i] for name in models) for i in range(n_queries)]

    cumulative_reward = 0.0
    cumulative_regret = 0.0
    reward_history = []
    regret_history = []
    selection_history = []

    for i in range(n_queries):
        arm = bandit.bandit.select_arm()
        reward = query_rewards[arm][i]
        optimal = optimal_rewards[i]
        regret = optimal - reward

        bandit.update(arm, reward)

        cumulative_reward += reward
        cumulative_regret += regret
        reward_history.append(cumulative_reward)
        regret_history.append(cumulative_regret)
        selection_history.append(arm)

    return SimulationResult(
        algorithm=algorithm,
        total_rounds=n_queries,
        cumulative_reward=cumulative_reward,
        cumulative_regret=cumulative_regret,
        arm_stats=bandit.get_stats(),
        reward_history=reward_history,
        regret_history=regret_history,
        selection_history=selection_history,
    )

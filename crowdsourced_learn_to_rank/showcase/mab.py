"""Multi-Armed Bandit algorithms for ranking model selection."""

import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import json
from datetime import datetime, timezone


class RankingModel(Protocol):
    def predict(self, X: np.ndarray) -> np.ndarray: ...


@dataclass
class ArmStats:
    """Statistics for a single arm (model)."""
    name: str
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls > 0 else 0.0


class UCB1:
    """Upper Confidence Bound algorithm for model selection."""

    def __init__(self, arm_names: list[str], c: float = 2.0):
        self.c = c
        self.arms = {name: ArmStats(name=name) for name in arm_names}
        self.total_pulls = 0

    def select_arm(self) -> str:
        """Select arm using UCB1 formula."""
        # First, try each arm once
        for name, stats in self.arms.items():
            if stats.pulls == 0:
                return name

        # UCB1 selection
        best_arm = None
        best_ucb = -float('inf')

        for name, stats in self.arms.items():
            exploration = self.c * np.sqrt(np.log(self.total_pulls) / stats.pulls)
            ucb = stats.mean_reward + exploration
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = name

        return best_arm

    def update(self, arm_name: str, reward: float):
        """Update arm statistics after receiving reward."""
        self.arms[arm_name].pulls += 1
        self.arms[arm_name].total_reward += reward
        self.total_pulls += 1

    def get_best_arm(self) -> str:
        """Return arm with highest mean reward."""
        return max(self.arms.values(), key=lambda a: a.mean_reward).name

    def get_stats(self) -> dict:
        """Return current statistics for all arms."""
        return {
            name: {
                "pulls": stats.pulls,
                "total_reward": stats.total_reward,
                "mean_reward": stats.mean_reward,
            }
            for name, stats in self.arms.items()
        }


class ThompsonSampling:
    """Thompson Sampling for model selection (Beta-Bernoulli)."""

    def __init__(self, arm_names: list[str]):
        # Beta prior: alpha=1, beta=1 (uniform)
        self.arms = {name: {"alpha": 1.0, "beta": 1.0, "pulls": 0} for name in arm_names}
        self.total_pulls = 0

    def select_arm(self) -> str:
        """Select arm by sampling from posterior."""
        samples = {
            name: np.random.beta(stats["alpha"], stats["beta"])
            for name, stats in self.arms.items()
        }
        return max(samples, key=samples.get)

    def update(self, arm_name: str, reward: float):
        """Update posterior with observed reward (0 or 1)."""
        if reward > 0:
            self.arms[arm_name]["alpha"] += 1
        else:
            self.arms[arm_name]["beta"] += 1
        self.arms[arm_name]["pulls"] += 1
        self.total_pulls += 1

    def get_best_arm(self) -> str:
        """Return arm with highest expected reward."""
        expected = {
            name: stats["alpha"] / (stats["alpha"] + stats["beta"])
            for name, stats in self.arms.items()
        }
        return max(expected, key=expected.get)

    def get_stats(self) -> dict:
        return {
            name: {
                "pulls": stats["pulls"],
                "alpha": stats["alpha"],
                "beta": stats["beta"],
                "expected_reward": stats["alpha"] / (stats["alpha"] + stats["beta"]),
            }
            for name, stats in self.arms.items()
        }


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
    ):
        self.models = models
        arm_names = list(models.keys())

        if algorithm == "ucb1":
            self.bandit = UCB1(arm_names, c=c)
        elif algorithm == "thompson":
            self.bandit = ThompsonSampling(arm_names)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        self.algorithm = algorithm

    def select_and_rank(self, X: np.ndarray) -> tuple[str, np.ndarray]:
        """Select a model and return rankings."""
        arm = self.bandit.select_arm()
        scores = self.models[arm].predict(X)
        return arm, scores

    def update(self, arm: str, reward: float):
        """Update bandit with observed reward."""
        self.bandit.update(arm, reward)

    def get_stats(self) -> dict:
        return self.bandit.get_stats()

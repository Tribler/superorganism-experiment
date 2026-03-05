"""Multi-Armed Bandit for ranking model selection."""

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


def simulate_bandit(
    models: dict[str, RankingModel],
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    algorithm: str = "ucb1",
    c: float = 2.0,
) -> SimulationResult:
    """
    Simulate MAB model selection on test queries.

    Reward: 1 if model ranks the relevant doc at position 1, else 0.
    """
    bandit = ModelBandit(models, algorithm=algorithm, c=c)

    # Precompute each model's predictions and "optimal" rewards per query
    model_scores = {name: model.predict(X) for name, model in models.items()}

    # Compute reward for each model on each query
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

    # Run simulation
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


if __name__ == "__main__":
    from ltr_evaluator import LETORDataset, load_model

    # Load models
    models_dir = Path(__file__).parent / "models"
    model_paths = [
        ("XGBoost", models_dir / "tribler_xgboost.json"),
        ("LightGBM", models_dir / "tribler_lightgbm.txt"),
        ("PDGD", models_dir / "pdgd_ranker.npy"),
    ]

    models = {}
    for name, path in model_paths:
        model, _ = load_model(path)
        models[name] = model

    # Load test data
    data_dir = Path(__file__).parent / "data" / "tribler_data" / "tribler_data" / "_normalized"
    dataset = LETORDataset(data_dir)
    X_test, y_test, _, groups_test = dataset.load_test()

    print(f"Running simulation on {len(groups_test)} queries...")
    print(f"Models: {list(models.keys())}")
    print()

    # Run both algorithms
    for algo in ["ucb1", "thompson"]:
        result = simulate_bandit(models, X_test, y_test, groups_test, algorithm=algo)

        print(f"=== {algo.upper()} ===")
        print(f"Total reward: {result.cumulative_reward:.0f} / {result.total_rounds}")
        print(f"Total regret: {result.cumulative_regret:.0f}")
        print(f"Reward rate: {result.cumulative_reward / result.total_rounds:.2%}")
        print("Arm stats:")
        for name, stats in result.arm_stats.items():
            pulls = stats["pulls"]
            mr = stats.get("mean_reward", stats.get("expected_reward", 0))
            print(f"  {name}: {pulls} pulls, {mr:.2%} reward")
        print()
"""Local 5-peer experiment with real LTR models, dataset replay, and survival-of-the-fittest.

This runs locally without DAS - useful for testing and debugging.

Features:
1. 5 peers with different initial models
2. 5 rounds of queries with gossip between rounds
3. MAB-based model selection (UCB1)
4. Gossip-based stats sharing between rounds
5. Survival-of-the-fittest: eliminate models with low performance after each round
"""
import json
import os
import sys
from asyncio import run, sleep, Event, Lock
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

from ipv8.community import Community, CommunitySettings
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer
from ipv8_service import IPv8

from mab import UCB1, ThompsonSampling, ArmStats
from datasets import get_dataset
from ltr_evaluator import load_model

# Configuration
NUM_PEERS = 5
NUM_ROUNDS = 5
QUERIES_PER_ROUND = 100  # Each peer processes this many queries per round
BASE_PORT = 8090
PEER_DISCOVERY_WAIT = 3
GOSSIP_ROUNDS = 3  # Number of gossip exchanges between query rounds
GOSSIP_DELAY = 0.5  # Delay between gossip messages
MAX_GOSSIP_PEERS = 2  # Each peer gossips to at most this many random neighbors per round
MIN_PULLS_FOR_ELIMINATION = 10  # Don't eliminate until arm has been tried this many times
ELIMINATION_THRESHOLD = 0.75  # Eliminate if reward < threshold * best_reward

# Experiment config
DATASET_ID = "istella"  # Dataset to replay
DATA_DIR = Path(__file__).parent / "data"
MODELS_DIR = Path(__file__).parent / "models"
LOGS_DIR = Path(__file__).parent / "logs"

LOG_FILE = LOGS_DIR / f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(message: str) -> None:
    timestamp = datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "]"
    LOGS_DIR.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    print(message)


@dataclass
class MABStatsMessage(DataClassPayload[10]):
    """MAB statistics from a peer."""
    sender_id: int
    arm_names: str  # JSON list
    pulls: str      # JSON list
    rewards: str    # JSON list


@dataclass
class ExclusionMessage(DataClassPayload[11]):
    """Announcement that a model has been excluded."""
    sender_id: int
    model_name: str
    reason: str
    round_num: int


@dataclass
class NewModelMessage(DataClassPayload[12]):
    """Announcement that a new model is available."""
    sender_id: int
    model_name: str


def compute_ndcg(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    """Compute NDCG@k for a single query."""
    if len(y_true) == 0:
        return 0.0

    order = np.argsort(-scores)
    y_sorted = y_true[order]

    gains = 2**y_sorted - 1
    discounts = np.log2(np.arange(2, len(gains) + 2))
    dcg = np.sum(gains[:k] / discounts[:k])

    ideal_order = np.argsort(-y_true)
    ideal_gains = 2**y_true[ideal_order] - 1
    idcg = np.sum(ideal_gains[:k] / discounts[:k])

    return dcg / idcg if idcg > 0 else 0.0


def compute_mrr(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    """Compute MRR@k (Mean Reciprocal Rank) for a single query.

    Returns 1/rank of the first relevant document within the top-k,
    or 0 if no relevant document appears in the top-k.
    """
    if len(y_true) == 0:
        return 0.0

    order = np.argsort(-scores)
    y_sorted = y_true[order]

    for i in range(min(k, len(y_sorted))):
        if y_sorted[i] > 0:
            return 1.0 / (i + 1)
    return 0.0


def precompute_model_scores(
    models: dict[str, Any],
    X: np.ndarray,
    y: np.ndarray,
    query_boundaries: list[tuple[int, int]],
    k_values: list[int] = [1, 5, 10],
    metric: str = "ndcg",
) -> dict[str, dict[int, list[float]]]:
    """Precompute metric@k for each model on each query.

    Args:
        metric: "ndcg" or "mrr"
    """
    compute_fn = compute_mrr if metric == "mrr" else compute_ndcg
    result = {}

    for name, model in models.items():
        scores = model.predict(X)
        result[name] = {k: [] for k in k_values}

        for start, end in query_boundaries:
            y_q = y[start:end]
            scores_q = scores[start:end]

            for k in k_values:
                value = compute_fn(y_q, scores_q, k)
                result[name][k].append(value)

    return result


class LTRMABCommunity(Community):
    """Community for LTR model selection via MAB with real models."""
    community_id = os.urandom(20)
    _peer_counter = 0
    _state = None  # Shared state

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)
        self.add_message_handler(MABStatsMessage, self.on_mab_stats)
        self.add_message_handler(ExclusionMessage, self.on_exclusion)
        self.add_message_handler(NewModelMessage, self.on_new_model)

        # Assign peer ID
        LTRMABCommunity._peer_counter += 1
        self.peer_id = LTRMABCommunity._peer_counter

        # Initialize MAB with initial models (excludes hot-swap model)
        model_names = list(self._state["initial_model_names"])
        algorithm = self._state.get("algorithm", "ucb1")
        if algorithm == "thompson":
            self.bandit = ThompsonSampling(model_names)
        else:
            self.bandit = UCB1(model_names, c=2.0)
        self.active_models = set(model_names)
        self.excluded_models = set()

        # Metric label
        self.metric = self._state.get("metric", "ndcg")

        # Tracking
        self.queries_processed = 0
        self.cumulative_scores = {1: 0.0, 5: 0.0, 10: 0.0}
        self.round_scores = {1: 0.0, 5: 0.0, 10: 0.0}
        self.round_queries = 0

    @classmethod
    def set_state(cls, state: dict):
        cls._state = state

    def started(self) -> None:
        log(f"[Peer {self.peer_id}] Started with models: {list(self.active_models)}")

    def _get_arm_pulls(self, name: str) -> int:
        """Get pull count for an arm, works with both UCB1 and ThompsonSampling."""
        arm = self.bandit.arms[name]
        return arm.pulls if isinstance(arm, ArmStats) else arm["pulls"]

    def select_active_arm(self) -> str | None:
        """Select arm only from active (non-excluded) models."""
        if not self.active_models:
            return None

        # First try untried active arms
        for name in self.active_models:
            if self._get_arm_pulls(name) == 0:
                return name

        if isinstance(self.bandit, ThompsonSampling):
            # Thompson Sampling among active arms only
            samples = {
                name: np.random.beta(self.bandit.arms[name]["alpha"], self.bandit.arms[name]["beta"])
                for name in self.active_models
            }
            return max(samples, key=samples.get)
        else:
            # UCB selection among active arms only
            best_arm = None
            best_ucb = -float('inf')

            for name in self.active_models:
                stats = self.bandit.arms[name]
                exploration = self.bandit.c * np.sqrt(np.log(self.bandit.total_pulls + 1) / (stats.pulls + 1))
                ucb = stats.mean_reward + exploration
                if ucb > best_ucb:
                    best_ucb = ucb
                    best_arm = name

            return best_arm

    def process_query(self, query_idx: int) -> tuple[str, float, float, float]:
        """Process a single query, return (model, score@1, score@5, score@10)."""
        state = self._state

        selected = self.select_active_arm()
        if selected is None:
            return None, 0, 0, 0

        # Get precomputed metric values
        model_scores = state["model_scores"]
        s1 = model_scores[selected][1][query_idx]
        s5 = model_scores[selected][5][query_idx]
        s10 = model_scores[selected][10][query_idx]

        # Update bandit (reward = metric@1)
        self.bandit.update(selected, s1)

        # Track
        self.queries_processed += 1
        self.round_queries += 1
        self.cumulative_scores[1] += s1
        self.cumulative_scores[5] += s5
        self.cumulative_scores[10] += s10
        self.round_scores[1] += s1
        self.round_scores[5] += s5
        self.round_scores[10] += s10

        return selected, s1, s5, s10

    def reset_round_stats(self):
        """Reset per-round statistics."""
        self.round_scores = {1: 0.0, 5: 0.0, 10: 0.0}
        self.round_queries = 0

    def get_round_summary(self) -> str:
        """Get summary of this round's performance."""
        if self.round_queries == 0:
            return "No queries processed"
        m = self.metric.upper()
        avg_1 = self.round_scores[1] / self.round_queries
        avg_5 = self.round_scores[5] / self.round_queries
        avg_10 = self.round_scores[10] / self.round_queries
        return f"{m}@1={avg_1:.3f}, {m}@5={avg_5:.3f}, {m}@10={avg_10:.3f}"

    async def send_gossip(self) -> int:
        """Send MAB statistics to a random subset of peers. Returns number of peers gossiped to."""
        peers = self.get_peers()
        if not peers:
            return 0

        # Pick a random subset of peers to gossip with
        if len(peers) > MAX_GOSSIP_PEERS:
            peers = list(np.random.choice(peers, size=MAX_GOSSIP_PEERS, replace=False))

        stats = self.bandit.get_stats()
        names = list(stats.keys())
        pulls = [stats[n]["pulls"] for n in names]
        # UCB1 has total_reward; Thompson has alpha-1 as total successes
        if isinstance(self.bandit, ThompsonSampling):
            rewards = [stats[n]["alpha"] - 1.0 for n in names]
        else:
            rewards = [stats[n]["total_reward"] for n in names]

        msg = MABStatsMessage(
            sender_id=self.peer_id,
            arm_names=json.dumps(names),
            pulls=json.dumps(pulls),
            rewards=json.dumps(rewards),
        )

        for peer in peers:
            self.ez_send(peer, msg)

        return len(peers)

    @lazy_wrapper(MABStatsMessage)
    def on_mab_stats(self, peer: Peer, payload: MABStatsMessage) -> None:
        """Merge MAB stats from peer."""
        names = json.loads(payload.arm_names)
        pulls = json.loads(payload.pulls)
        rewards = json.loads(payload.rewards)

        merged_any = False
        merge_details = []

        for name, remote_pulls, remote_reward in zip(names, pulls, rewards):
            if name not in self.bandit.arms:
                continue

            local_arm = self.bandit.arms[name]
            if isinstance(local_arm, ArmStats):
                # UCB1
                if remote_pulls > local_arm.pulls:
                    diff = remote_pulls - local_arm.pulls
                    old_pulls = local_arm.pulls
                    local_arm.pulls = remote_pulls
                    local_arm.total_reward = remote_reward
                    self.bandit.total_pulls += diff
                    merged_any = True
                    merge_details.append(f"{name}: {old_pulls}->{remote_pulls} pulls")
            else:
                # ThompsonSampling (dict with alpha/beta/pulls)
                if remote_pulls > local_arm["pulls"]:
                    old_pulls = local_arm["pulls"]
                    # Approximate: set alpha/beta from total reward counts
                    if remote_pulls > 0:
                        local_arm["alpha"] = 1.0 + remote_reward
                        local_arm["beta"] = 1.0 + (remote_pulls - remote_reward)
                    local_arm["pulls"] = remote_pulls
                    self.bandit.total_pulls += remote_pulls - old_pulls
                    merged_any = True
                    merge_details.append(f"{name}: {old_pulls}->{remote_pulls} pulls")

        if merged_any:
            log(f"[Peer {self.peer_id}] GOSSIP RECEIVED from Peer {payload.sender_id}: merged [{', '.join(merge_details)}]")

    def _get_mean_reward(self, stats_entry: dict) -> float:
        """Get mean/expected reward from stats, works with both UCB1 and Thompson."""
        return stats_entry.get("mean_reward", stats_entry.get("expected_reward", 0.0))

    def check_exclusions(self, round_num: int) -> list[str]:
        """Check and exclude poorly performing models. Returns list of excluded models."""
        if len(self.active_models) <= 1:
            return []

        stats = self.bandit.get_stats()
        active_stats = {name: stats[name] for name in self.active_models}

        # Find best performer
        best_name = max(active_stats, key=lambda n: self._get_mean_reward(active_stats[n]))
        best_reward = self._get_mean_reward(active_stats[best_name])

        if best_reward == 0:
            return []

        excluded = []
        for name in list(self.active_models):
            s = stats[name]
            if s["pulls"] < MIN_PULLS_FOR_ELIMINATION:
                continue

            mr = self._get_mean_reward(s)
            if mr < ELIMINATION_THRESHOLD * best_reward:
                self.exclude_model(name, round_num, best_name, best_reward, mr)
                excluded.append(name)

        return excluded

    def exclude_model(self, name: str, round_num: int, best_name: str, best_reward: float, model_reward: float) -> None:
        """Exclude a model from future selection."""
        if name not in self.active_models:
            return

        self.active_models.remove(name)
        self.excluded_models.add(name)

        log(f"")
        log(f"{'#'*70}")
        log(f"[Peer {self.peer_id}] ARM EXCLUDED: {name}")
        log(f"[Peer {self.peer_id}]   Round: {round_num}")
        log(f"[Peer {self.peer_id}]   Reason: mean_reward={model_reward:.3f} < {ELIMINATION_THRESHOLD}*{best_reward:.3f} (best={best_name})")
        log(f"[Peer {self.peer_id}]   Remaining active: {list(self.active_models)}")
        log(f"{'#'*70}")
        log(f"")

    async def broadcast_exclusion(self, model_name: str, round_num: int, reason: str) -> None:
        """Broadcast exclusion to a random subset of peers."""
        msg = ExclusionMessage(
            sender_id=self.peer_id,
            model_name=model_name,
            reason=reason,
            round_num=round_num,
        )
        peers = self.get_peers()
        if len(peers) > MAX_GOSSIP_PEERS:
            peers = list(np.random.choice(peers, size=MAX_GOSSIP_PEERS, replace=False))
        for peer in peers:
            self.ez_send(peer, msg)

    @lazy_wrapper(ExclusionMessage)
    def on_exclusion(self, peer: Peer, payload: ExclusionMessage) -> None:
        """Handle exclusion announcement from peer."""
        if payload.model_name in self.active_models:
            self.active_models.remove(payload.model_name)
            self.excluded_models.add(payload.model_name)
            log(f"[Peer {self.peer_id}] ARM EXCLUDED (via gossip from Peer {payload.sender_id}): {payload.model_name}")
            log(f"[Peer {self.peer_id}]   Reason: {payload.reason}")

    def add_model(self, model_name: str) -> None:
        """Hot-swap: add a new model to this peer's MAB."""
        if model_name in self.bandit.arms:
            return
        state = self._state
        if model_name not in state["model_scores"]:
            log(f"[Peer {self.peer_id}] Cannot add {model_name}: no precomputed scores")
            return

        if isinstance(self.bandit, ThompsonSampling):
            self.bandit.arms[model_name] = {"alpha": 1.0, "beta": 1.0, "pulls": 0}
        else:
            self.bandit.arms[model_name] = ArmStats(name=model_name)
        self.active_models.add(model_name)
        log(f"[Peer {self.peer_id}] HOT-SWAP: Added {model_name} to MAB")
        log(f"[Peer {self.peer_id}]   Active models: {sorted(self.active_models)}")

    async def propose_model(self, model_name: str) -> None:
        """Propose a new model: add locally and announce to neighbors."""
        self.add_model(model_name)
        peers = self.get_peers()
        if len(peers) > MAX_GOSSIP_PEERS:
            peers = list(np.random.choice(peers, size=MAX_GOSSIP_PEERS, replace=False))
        msg = NewModelMessage(sender_id=self.peer_id, model_name=model_name)
        for peer in peers:
            self.ez_send(peer, msg)
        log(f"[Peer {self.peer_id}] PROPOSED {model_name} to {len(peers)} peers")

    @lazy_wrapper(NewModelMessage)
    def on_new_model(self, peer: Peer, payload: NewModelMessage) -> None:
        """Handle new model announcement from a peer and forward to neighbors."""
        if payload.model_name in self.bandit.arms:
            return
        log(f"[Peer {self.peer_id}] RECEIVED new model announcement: {payload.model_name} from Peer {payload.sender_id}")
        self.add_model(payload.model_name)

        # Forward to neighbors (epidemic gossip)
        msg = NewModelMessage(sender_id=self.peer_id, model_name=payload.model_name)
        peers = self.get_peers()
        if len(peers) > MAX_GOSSIP_PEERS:
            peers = list(np.random.choice(peers, size=MAX_GOSSIP_PEERS, replace=False))
        for p in peers:
            self.ez_send(p, msg)

    def print_arm_stats(self) -> None:
        """Print current arm statistics."""
        stats = self.bandit.get_stats()
        log(f"[Peer {self.peer_id}] Current arm statistics:")
        for name in sorted(stats.keys(), key=lambda n: -self._get_mean_reward(stats[n])):
            s = stats[name]
            mr = self._get_mean_reward(s)
            status = "EXCLUDED" if name in self.excluded_models else "ACTIVE"
            log(f"[Peer {self.peer_id}]   [{status:8}] {name}: pulls={s['pulls']:3d}, mean_reward={mr:.4f}")


def load_experiment_models(dataset_id: str) -> dict[str, Any]:
    """Load trained models for a dataset."""
    models = {}

    for meta_file in MODELS_DIR.glob(f"{dataset_id}_*.meta.json"):
        model_file = Path(str(meta_file).replace(".meta.json", ""))
        if not model_file.exists():
            continue

        try:
            model, meta = load_model(model_file)
            models[meta.name] = model
            log(f"Loaded: {meta.name} from {model_file.name}")
        except Exception as e:
            log(f"Failed to load {model_file}: {e}")

    return models


async def run_local_experiment(
    dataset_id: str = DATASET_ID,
    num_peers: int = NUM_PEERS,
    num_rounds: int = NUM_ROUNDS,
    queries_per_round: int = QUERIES_PER_ROUND,
    gossip_enabled: bool = True,
    hotswap_round: int = 0,
    algorithm: str = "ucb1",
    metric: str = "ndcg",
    dashboard_state=None,
) -> None:
    """Run local experiment with N peers and R rounds."""
    # Stub dashboard if not provided (CLI mode)
    if dashboard_state is None:
        class _Noop:
            communities = []
            current_round = 0
            phase = ""
            config = {}
            oracle = {}
            round_history = []
            def event(self, *a, **k): pass
        dashboard_state = _Noop()

    LOGS_DIR.mkdir(exist_ok=True)

    log("=" * 70)
    log("Local LTR MAB Experiment with Survival-of-the-Fittest")
    log("=" * 70)
    log(f"Dataset: {dataset_id}")
    log(f"Peers: {num_peers}")
    log(f"Rounds: {num_rounds}")
    log(f"Queries per peer per round: {queries_per_round}")
    log(f"Total queries: {num_peers * num_rounds * queries_per_round}")
    log(f"Algorithm: {algorithm}")
    log(f"Metric: {metric.upper()}")
    log(f"Exclusion threshold: {ELIMINATION_THRESHOLD}")
    log("=" * 70)

    # Load models
    log("\nLoading models...")
    models = load_experiment_models(dataset_id)
    if not models:
        log(f"ERROR: No models found for {dataset_id}")
        return
    log(f"Loaded {len(models)} models: {list(models.keys())}")

    # Separate XGBoost for hot-swap if enabled
    hotswap_model_name = None
    if hotswap_round > 0:
        # Find the xgboost model
        xgb_names = [n for n in models if "xgboost" in n.lower()]
        if xgb_names:
            hotswap_model_name = xgb_names[0]
            log(f"Hot-swap enabled: {hotswap_model_name} will be proposed at round {hotswap_round}")
        else:
            log("WARNING: Hot-swap enabled but no XGBoost model found, disabling")
            hotswap_round = 0

    # Load dataset
    log("\nLoading dataset...")
    dataset = get_dataset(dataset_id, DATA_DIR, fold=1)
    X_test, y_test, _, groups = dataset.load_test()
    log(f"Test set: {X_test.shape[0]} samples, {len(groups)} queries")

    # Compute query boundaries
    query_boundaries = []
    start = 0
    for g in groups:
        query_boundaries.append((start, start + g))
        start += g

    # Precompute metric scores for all models
    metric_label = metric.upper()
    log(f"\nPrecomputing {metric_label} for all models...")
    model_scores = precompute_model_scores(models, X_test, y_test, query_boundaries, metric=metric)

    log("\nOracle performance (always using each model):")
    oracle = {}
    for name in models:
        avg_10 = np.mean(model_scores[name][10])
        oracle[name] = avg_10
        log(f"  {name}: avg {metric_label}@10 = {avg_10:.4f}")

    # Update dashboard state
    dashboard_state.config = {
        "dataset": dataset_id,
        "num_peers": num_peers,
        "num_rounds": num_rounds,
        "queries_per_round": queries_per_round,
        "algorithm": algorithm,
        "metric": metric,
    }
    dashboard_state.oracle = oracle

    # Initial models exclude the hot-swap model (if any)
    initial_model_names = [n for n in models if n != hotswap_model_name]

    # Create shared state
    state = {
        "models": models,
        "initial_model_names": initial_model_names,
        "model_scores": model_scores,
        "query_boundaries": query_boundaries,
        "num_queries": len(query_boundaries),
        "algorithm": algorithm,
        "metric": metric,
    }
    LTRMABCommunity.set_state(state)

    # Reset peer counter
    LTRMABCommunity._peer_counter = 0

    # Start peers
    log(f"\n{'='*70}")
    log(f"Starting {num_peers} peers...")
    log(f"{'='*70}")
    instances = []

    for i in range(num_peers):
        port = BASE_PORT + i
        builder = ConfigBuilder().clear_keys().clear_overlays()
        builder.add_key("my peer", "medium", f"peer{i+1}.pem")
        builder.set_port(port)
        builder.add_overlay(
            "LTRMABCommunity", "my peer",
            [WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
            default_bootstrap_defs, {}, [("started",)]
        )

        ipv8 = IPv8(builder.finalize(), extra_communities={"LTRMABCommunity": LTRMABCommunity})
        await ipv8.start()
        instances.append(ipv8)

    # Wait for peer discovery
    log(f"\nWaiting {PEER_DISCOVERY_WAIT}s for peer discovery...")
    await sleep(PEER_DISCOVERY_WAIT)

    communities = [inst.get_overlay(LTRMABCommunity) for inst in instances]
    dashboard_state.communities = communities
    for comm in communities:
        log(f"Peer {comm.peer_id}: connected to {len(comm.get_peers())} peers")

    # Query pool
    total_queries = len(query_boundaries)
    rng = np.random.default_rng()

    # Run rounds
    for round_num in range(1, num_rounds + 1):
        dashboard_state.current_round = round_num
        log(f"\n{'='*70}")
        log(f"ROUND {round_num}/{num_rounds}")
        log(f"{'='*70}")
        dashboard_state.event(f"Round {round_num}/{num_rounds} started", "round")

        # Reset round stats
        for comm in communities:
            comm.reset_round_stats()

        # Each peer processes queries (randomized independently per peer)
        dashboard_state.phase = "querying"
        log(f"\n--- Query Phase (Round {round_num}) ---")
        for comm in communities:
            log(f"[Peer {comm.peer_id}] Processing {queries_per_round} queries...")

            replace = queries_per_round > total_queries
            query_indices = rng.choice(total_queries, size=queries_per_round, replace=replace)
            for query_idx in query_indices:
                comm.process_query(int(query_idx))

            log(f"[Peer {comm.peer_id}] Round {round_num} complete: {comm.get_round_summary()}")
            await sleep(0.01)  # let dashboard poll

        # Hot-swap: a random peer proposes XGBoost at the configured round
        if hotswap_round > 0 and round_num == hotswap_round and hotswap_model_name:
            proposer = communities[rng.integers(len(communities))]
            log(f"\n{'#'*70}")
            log(f"HOT-SWAP: Peer {proposer.peer_id} proposing {hotswap_model_name}")
            log(f"{'#'*70}")
            dashboard_state.event(f"HOT-SWAP: Peer {proposer.peer_id} proposing {hotswap_model_name}", "round")
            await proposer.propose_model(hotswap_model_name)
            await sleep(0.5)  # let announcement propagate

        # Gossip phase
        if gossip_enabled:
            dashboard_state.phase = "gossiping"
            log(f"\n--- Gossip Phase (Round {round_num}) ---")
            for gossip_round in range(1, GOSSIP_ROUNDS + 1):
                log(f"[Gossip round {gossip_round}/{GOSSIP_ROUNDS}]")
                for comm in communities:
                    n_peers = await comm.send_gossip()
                    if n_peers > 0:
                        stats = comm.bandit.get_stats()
                        total_pulls = sum(s["pulls"] for s in stats.values())
                        log(f"[Peer {comm.peer_id}] GOSSIP SENT to {n_peers} peers (total_pulls={total_pulls})")
                        dashboard_state.event(f"Peer {comm.peer_id} gossiped to {n_peers} peers", "gossip")
                await sleep(GOSSIP_DELAY)
        else:
            log(f"\n--- Gossip Phase (Round {round_num}) --- SKIPPED (disabled)")
            dashboard_state.event("Gossip skipped (disabled)", "info")

        # Print arm stats after gossip
        log(f"\n--- Arm Statistics (after Round {round_num}) ---")
        for comm in communities:
            comm.print_arm_stats()

        # Survival check (exclusion phase)
        dashboard_state.phase = "survival"
        log(f"\n--- Survival Check (Round {round_num}) ---")
        all_excluded = set()
        for comm in communities:
            excluded = comm.check_exclusions(round_num)
            for model_name in excluded:
                if model_name not in all_excluded:
                    all_excluded.add(model_name)
                    stats = comm.bandit.get_stats()
                    reason = f"mean_reward={comm._get_mean_reward(stats[model_name]):.3f}"
                    if gossip_enabled:
                        await comm.broadcast_exclusion(model_name, round_num, reason)
                    dashboard_state.event(f"ARM EXCLUDED: {model_name} ({reason})", "exclusion")
                    await sleep(0.1)

        if not all_excluded:
            log(f"[Round {round_num}] No models excluded this round")

        # Record round history for charts
        arm_pulls = {}  # arm -> total pulls across all peers
        arm_reward_sum = {}  # arm -> sum of mean_rewards across peers
        arm_reward_count = {}  # arm -> number of peers that have stats for this arm
        total_cumulative_reward = 0.0
        total_queries_all = 0

        for comm in communities:
            stats = comm.bandit.get_stats()
            for name, s in stats.items():
                arm_pulls[name] = arm_pulls.get(name, 0) + s["pulls"]
                mr = comm._get_mean_reward(s)
                arm_reward_sum[name] = arm_reward_sum.get(name, 0.0) + mr
                arm_reward_count[name] = arm_reward_count.get(name, 0) + 1
            total_cumulative_reward += comm.cumulative_scores.get(10, 0.0)
            total_queries_all += comm.queries_processed

        # Oracle cumulative reward: best single model's avg score * total queries
        best_oracle_score = max(oracle.values()) if oracle else 0
        oracle_cumulative = best_oracle_score * total_queries_all

        # Arms that appear for the first time this round (hot-swap introductions)
        prev_arms = set(dashboard_state.round_history[-1]["arm_pulls"].keys()) if dashboard_state.round_history else set()
        new_arms = [name for name in arm_pulls if name not in prev_arms]

        round_snapshot = {
            "round": round_num,
            "arm_pulls": arm_pulls,
            "arm_mean_reward": {
                name: round(arm_reward_sum[name] / arm_reward_count[name], 4)
                for name in arm_reward_sum
            },
            "cumulative_reward": round(total_cumulative_reward, 4),
            "oracle_cumulative": round(oracle_cumulative, 4),
            "new_arms": new_arms,
        }
        dashboard_state.round_history.append(round_snapshot)

        # Brief summary
        log(f"\n--- Round {round_num} Summary ---")
        for comm in communities:
            best = comm.bandit.get_best_arm()
            log(f"[Peer {comm.peer_id}] Best model: {best}, Active: {len(comm.active_models)}, Excluded: {len(comm.excluded_models)}")

    # Final results
    dashboard_state.phase = "finished"
    dashboard_state.event("Experiment complete", "round")
    log(f"\n{'='*70}")
    log("FINAL RESULTS")
    log(f"{'='*70}")

    for comm in communities:
        log(f"\n[Peer {comm.peer_id}] === FINAL STATISTICS ===")
        log(f"[Peer {comm.peer_id}] Total queries: {comm.queries_processed}")
        if comm.queries_processed > 0:
            log(f"[Peer {comm.peer_id}] Average {metric_label}@1:  {comm.cumulative_scores[1] / comm.queries_processed:.4f}")
            log(f"[Peer {comm.peer_id}] Average {metric_label}@5:  {comm.cumulative_scores[5] / comm.queries_processed:.4f}")
            log(f"[Peer {comm.peer_id}] Average {metric_label}@10: {comm.cumulative_scores[10] / comm.queries_processed:.4f}")
        log(f"[Peer {comm.peer_id}] Best model: {comm.bandit.get_best_arm()}")
        log(f"[Peer {comm.peer_id}] Excluded models: {comm.excluded_models}")
        comm.print_arm_stats()

    # Save results
    results_file = LOGS_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    all_results = []
    for comm in communities:
        all_results.append({
            "peer_id": comm.peer_id,
            "queries_processed": comm.queries_processed,
            "cumulative_scores": {str(k): v for k, v in comm.cumulative_scores.items()},
            "arm_stats": comm.bandit.get_stats(),
            "excluded": list(comm.excluded_models),
            "best_model": comm.bandit.get_best_arm(),
        })

    with open(results_file, "w") as f:
        json.dump({
            "dataset": dataset_id,
            "algorithm": algorithm,
            "metric": metric,
            "num_peers": num_peers,
            "num_rounds": num_rounds,
            "queries_per_round": queries_per_round,
            "models": list(models.keys()),
            "peers": all_results,
        }, f, indent=2)

    log(f"\nResults saved to: {results_file}")
    log(f"Log saved to: {LOG_FILE}")

    # Cleanup IPv8 instances
    for inst in instances:
        await inst.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run local MAB experiment")
    parser.add_argument("--dataset", default=DATASET_ID, help="Dataset to use")
    parser.add_argument("--peers", type=int, default=NUM_PEERS, help="Number of peers")
    parser.add_argument("--rounds", type=int, default=NUM_ROUNDS, help="Number of rounds")
    parser.add_argument("--queries", type=int, default=QUERIES_PER_ROUND, help="Queries per peer per round")
    parser.add_argument("--no-gossip", action="store_true", help="Disable gossip between peers")
    parser.add_argument("--hotswap-round", type=int, default=0, help="Round at which XGBoost is proposed (0=disabled)")
    parser.add_argument("--algorithm", choices=["ucb1", "thompson"], default="ucb1", help="MAB algorithm")
    parser.add_argument("--metric", choices=["ndcg", "mrr"], default="ndcg", help="Reward metric")
    args = parser.parse_args()

    run(run_local_experiment(
        dataset_id=args.dataset,
        num_peers=args.peers,
        num_rounds=args.rounds,
        queries_per_round=args.queries,
        gossip_enabled=not args.no_gossip,
        hotswap_round=args.hotswap_round,
        algorithm=args.algorithm,
        metric=args.metric,
    ))

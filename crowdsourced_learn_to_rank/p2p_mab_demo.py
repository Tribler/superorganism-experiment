"""P2P Multi-Armed Bandit demo for ranking model selection with model hot-swap.

Two peers share MAB statistics via gossip to converge on the best ranking model.
When a peer has a model that others don't, it shares it via BitTorrent.

This demonstrates:
1. Decentralized model selection using Multi-Armed Bandits
2. Gossip-based statistics sharing between peers
3. BitTorrent-based model distribution with hot-swap capability
"""
import json
import os
from asyncio import run, sleep
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import libtorrent as lt
import numpy as np

from ipv8.community import Community, CommunitySettings
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer
from ipv8.util import run_forever
from ipv8_service import IPv8

from mab import UCB1, ArmStats

# Constants
PEER1_PORT = 8090
PEER2_PORT = 8091
BT_SEEDER_PORT = 6882
BT_DOWNLOADER_PORT = 6881
PEER_DISCOVERY_WAIT = 3
GOSSIP_INTERVAL = 2.0
SIMULATION_QUERIES = 100
MODEL_ANNOUNCE_DELAY = 10  # Seconds before Peer 1 announces new model

# Simulated model rewards (probability of click@1 for each model)
MODEL_REWARDS = {
    "ModelA": 0.23,
    "ModelB": 0.25,
    "ModelC": 0.19,
}

# New model that Peer 1 will share (better than all others)
NEW_MODEL_NAME = "SuperModel"
NEW_MODEL_REWARD = 0.35  # 35% click rate - best model

LOG_FILE = Path(__file__).parent / "mab_demo.log"
MODELS_DIR = Path(__file__).parent / "models"


def log(message: str) -> None:
    timestamp = datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "]"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    print(message)


@dataclass
class MABStatsMessage(DataClassPayload[10]):
    """Message containing MAB statistics from a peer."""
    sender_id: int
    arm_names: str  # JSON-encoded list
    pulls: str      # JSON-encoded list of pull counts
    rewards: str    # JSON-encoded list of total rewards


@dataclass
class NewModelMessage(DataClassPayload[11]):
    """Announcement of a new model available for download."""
    model_name: str
    magnet_uri: str
    seeder_host: str
    seeder_port: int


class MABCommunity(Community):
    """Community that uses MAB to select ranking models and shares stats via gossip."""
    community_id = os.urandom(20)
    _peer_counter = 0

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)
        self.add_message_handler(MABStatsMessage, self.on_mab_stats)
        self.add_message_handler(NewModelMessage, self.on_new_model)

        # Initialize MAB with base model names
        self.model_rewards = dict(MODEL_REWARDS)  # Local copy of known rewards
        self.bandit = UCB1(list(self.model_rewards.keys()), c=2.0)

        # Track state
        self.queries_processed = 0
        self.lt_session = None
        self.announced_models = set()  # Models we've already announced

        # Assign peer ID
        MABCommunity._peer_counter += 1
        self.peer_id = MABCommunity._peer_counter

    def started(self) -> None:
        log(f"[Peer {self.peer_id}] Started with MAB (UCB1), models: {list(self.model_rewards.keys())}")

        # Start simulating queries
        self.register_task("simulate_queries", self.simulate_query, interval=0.5, delay=1.0)

        # Start gossiping stats
        self.register_task("gossip_stats", self.gossip_stats, interval=GOSSIP_INTERVAL, delay=PEER_DISCOVERY_WAIT)

        # Peer 1 will announce a new model after delay
        if self.peer_id == 1:
            self.register_task("announce_new_model", self.announce_new_model, delay=MODEL_ANNOUNCE_DELAY)

    async def announce_new_model(self) -> None:
        """Peer 1 announces and seeds a new model."""
        log(f"\n{'='*60}")
        log(f"[Peer {self.peer_id}] ANNOUNCING NEW MODEL: {NEW_MODEL_NAME}")
        log(f"{'='*60}")

        # Add new model to local MAB
        self.add_model(NEW_MODEL_NAME, NEW_MODEL_REWARD)

        # Create model file
        MODELS_DIR.mkdir(exist_ok=True)
        model_file = MODELS_DIR / f"{NEW_MODEL_NAME}.json"
        model_data = {
            "name": NEW_MODEL_NAME,
            "type": "simulated",
            "reward_prob": NEW_MODEL_REWARD,
            "created_by": f"Peer {self.peer_id}",
        }
        with open(model_file, "w") as f:
            json.dump(model_data, f, indent=2)
        log(f"[Peer {self.peer_id}] Created model file: {model_file}")

        # Create torrent and start seeding
        magnet_uri = self.create_torrent_and_seed(model_file, BT_SEEDER_PORT)

        # Send announcement to all peers
        await sleep(0.5)  # Let seeder initialize
        for peer in self.get_peers():
            self.ez_send(peer, NewModelMessage(
                model_name=NEW_MODEL_NAME,
                magnet_uri=magnet_uri,
                seeder_host="127.0.0.1",
                seeder_port=BT_SEEDER_PORT,
            ))
            log(f"[Peer {self.peer_id}] Sent model announcement to {peer}")

        self.announced_models.add(NEW_MODEL_NAME)

    def create_torrent_and_seed(self, file_path: Path, port: int) -> str:
        """Create torrent for file and start seeding. Returns magnet URI."""
        fs = lt.file_storage()
        lt.add_files(fs, str(file_path))
        tor = lt.create_torrent(fs)
        tor.set_creator("MAB Model Sharing")
        lt.set_piece_hashes(tor, str(file_path.parent))
        torrent_info = lt.torrent_info(lt.bencode(tor.generate()))

        info_hash = torrent_info.info_hashes().v1
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn={file_path.name}"

        self.lt_session = lt.session({'listen_interfaces': f'0.0.0.0:{port}'})
        self.lt_session.add_torrent({'ti': torrent_info, 'save_path': str(file_path.parent)})
        log(f"[Peer {self.peer_id}] Seeding {file_path.name} on port {port}")

        return magnet_uri

    @lazy_wrapper(NewModelMessage)
    def on_new_model(self, peer: Peer, payload: NewModelMessage) -> None:
        """Handle announcement of a new model."""
        if payload.model_name in self.model_rewards:
            log(f"[Peer {self.peer_id}] Already have model {payload.model_name}, ignoring")
            return

        log(f"\n{'='*60}")
        log(f"[Peer {self.peer_id}] RECEIVED NEW MODEL ANNOUNCEMENT: {payload.model_name}")
        log(f"{'='*60}")

        self.register_anonymous_task(
            "download_model",
            self.download_and_add_model,
            payload.model_name,
            payload.magnet_uri,
            payload.seeder_host,
            payload.seeder_port,
        )

    async def download_and_add_model(self, model_name: str, magnet_uri: str,
                                      seeder_host: str, seeder_port: int) -> None:
        """Download model via BitTorrent and add to MAB."""
        log(f"[Peer {self.peer_id}] Downloading model {model_name} via BitTorrent...")

        # Initialize downloader session
        self.lt_session = lt.session({'listen_interfaces': f'0.0.0.0:{BT_DOWNLOADER_PORT}'})

        params = lt.parse_magnet_uri(magnet_uri)
        MODELS_DIR.mkdir(exist_ok=True)
        params.save_path = str(MODELS_DIR)

        handle = self.lt_session.add_torrent(params)
        handle.connect_peer((seeder_host, seeder_port))

        # Wait for download
        for i in range(30):  # 30 second timeout
            status = handle.status()
            if status.is_finished or status.progress >= 1.0:
                break
            log(f"[Peer {self.peer_id}] Download progress: {status.progress*100:.1f}%")
            await sleep(1)

        if not handle.status().is_finished:
            log(f"[Peer {self.peer_id}] Download timeout!")
            return

        log(f"[Peer {self.peer_id}] Download complete!")

        # Load model file and extract reward probability
        model_file = MODELS_DIR / f"{model_name}.json"
        if model_file.exists():
            with open(model_file) as f:
                model_data = json.load(f)
            reward_prob = model_data.get("reward_prob", 0.2)
            log(f"[Peer {self.peer_id}] Loaded model with reward_prob={reward_prob}")
        else:
            reward_prob = 0.2  # Default

        # Add model to MAB (hot-swap!)
        self.add_model(model_name, reward_prob)

        log(f"\n{'='*60}")
        log(f"[Peer {self.peer_id}] HOT-SWAP COMPLETE! Added {model_name} to MAB")
        log(f"[Peer {self.peer_id}] Active models: {list(self.model_rewards.keys())}")
        log(f"{'='*60}\n")

    def add_model(self, name: str, reward_prob: float) -> None:
        """Add a new model to the MAB."""
        if name in self.model_rewards:
            return

        self.model_rewards[name] = reward_prob
        self.bandit.arms[name] = ArmStats(name=name)
        log(f"[Peer {self.peer_id}] Added model {name} to MAB (reward_prob={reward_prob})")

    async def simulate_query(self) -> None:
        """Simulate a search query and update MAB based on simulated click."""
        if self.queries_processed >= SIMULATION_QUERIES:
            self.cancel_pending_task("simulate_queries")
            log(f"[Peer {self.peer_id}] Finished {SIMULATION_QUERIES} queries")
            self.print_final_stats()
            return

        # Select model using MAB
        selected_arm = self.bandit.select_arm()

        # Simulate reward (Bernoulli with model's true probability)
        true_prob = self.model_rewards.get(selected_arm, 0.2)
        reward = 1.0 if np.random.random() < true_prob else 0.0

        # Update bandit
        self.bandit.update(selected_arm, reward)
        self.queries_processed += 1

        if self.queries_processed % 20 == 0:
            stats = self.bandit.get_stats()
            best = max(stats.items(), key=lambda x: x[1]["mean_reward"])
            log(f"[Peer {self.peer_id}] Query {self.queries_processed}: selected={selected_arm}, "
                f"reward={reward:.0f}, best={best[0]} ({best[1]['mean_reward']:.1%})")

    async def gossip_stats(self) -> None:
        """Send MAB statistics to peers."""
        peers = self.get_peers()
        if not peers:
            return

        stats = self.bandit.get_stats()
        names = list(stats.keys())
        pulls = [stats[n]["pulls"] for n in names]
        rewards = [stats[n]["total_reward"] for n in names]

        msg = MABStatsMessage(
            sender_id=self.peer_id,
            arm_names=json.dumps(names),
            pulls=json.dumps(pulls),
            rewards=json.dumps(rewards),
        )

        for peer in peers:
            self.ez_send(peer, msg)

    @lazy_wrapper(MABStatsMessage)
    def on_mab_stats(self, peer: Peer, payload: MABStatsMessage) -> None:
        """Receive and merge MAB statistics from another peer."""
        names = json.loads(payload.arm_names)
        pulls = json.loads(payload.pulls)
        rewards = json.loads(payload.rewards)

        merged = False
        for name, remote_pulls, remote_reward in zip(names, pulls, rewards):
            if name not in self.bandit.arms:
                # Unknown model - request it from peer
                log(f"[Peer {self.peer_id}] Peer {payload.sender_id} has unknown model: {name}")
                continue

            local_stats = self.bandit.arms[name]
            if remote_pulls > local_stats.pulls:
                diff_pulls = remote_pulls - local_stats.pulls
                local_stats.pulls = remote_pulls
                local_stats.total_reward = remote_reward
                self.bandit.total_pulls += diff_pulls
                merged = True

        if merged:
            best = self.bandit.get_best_arm()
            log(f"[Peer {self.peer_id}] Merged stats from Peer {payload.sender_id}, best={best}")

    def print_final_stats(self) -> None:
        """Print final MAB statistics."""
        stats = self.bandit.get_stats()
        log(f"\n[Peer {self.peer_id}] === FINAL STATS ===")
        for name, s in stats.items():
            log(f"  {name}: {s['pulls']} pulls, {s['mean_reward']:.1%} reward")
        log(f"  Best model: {self.bandit.get_best_arm()}")
        log(f"  Total pulls: {self.bandit.total_pulls}")


async def start_mab_demo() -> None:
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    # Clean up old model files
    if MODELS_DIR.exists():
        for f in MODELS_DIR.glob("*.json"):
            f.unlink()

    log("=" * 60)
    log("P2P Multi-Armed Bandit Demo with Model Hot-Swap")
    log("=" * 60)
    log(f"Initial models: {list(MODEL_REWARDS.keys())}")
    log(f"Peer 1 will announce '{NEW_MODEL_NAME}' (reward={NEW_MODEL_REWARD}) after {MODEL_ANNOUNCE_DELAY}s")
    log("=" * 60)

    instances = []
    ports = [PEER1_PORT, PEER2_PORT]

    for i, port in enumerate(ports, 1):
        builder = ConfigBuilder().clear_keys().clear_overlays()
        builder.add_key("my peer", "medium", f"peer{i}.pem")
        builder.set_port(port)
        builder.add_overlay("MABCommunity", "my peer",
                            [WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
                            default_bootstrap_defs, {}, [("started",)])

        ipv8 = IPv8(builder.finalize(), extra_communities={"MABCommunity": MABCommunity})
        await ipv8.start()
        instances.append(ipv8)
        log(f"Started Peer {i} on port {port}")

    log(f"\nWaiting {PEER_DISCOVERY_WAIT}s for peer discovery...")
    await sleep(PEER_DISCOVERY_WAIT)

    for i, inst in enumerate(instances, 1):
        community = inst.get_overlay(MABCommunity)
        peers = community.get_peers()
        log(f"Peer {i} has {len(peers)} connected peers")

    log("\nStarting MAB simulation with model hot-swap...")
    log("-" * 60)

    await run_forever()


if __name__ == "__main__":
    run(start_mab_demo())

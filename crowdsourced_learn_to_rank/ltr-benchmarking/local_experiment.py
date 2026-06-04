"""Local 5-peer experiment with real LTR models, dataset replay, and survival-of-the-fittest.

This runs locally without DAS - useful for testing and debugging.

Features:
1. 5 peers with different initial models
2. 5 rounds of queries with gossip between rounds
3. MAB-based model selection (UCB1)
4. Gossip-based stats sharing between rounds
5. Survival-of-the-fittest: eliminate models with low performance after each round
"""
import base64
import hashlib
import json
import os
import struct
import sys
import asyncio
from asyncio import run, sleep, Event, Lock
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    import libtorrent as lt
except ImportError:  # pragma: no cover — hard dep, but keep import error readable
    lt = None

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

from ipv8.community import Community, CommunitySettings
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.keyvault.crypto import default_eccrypto
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer
from ipv8_service import IPv8

from mab import UCB1, ThompsonSampling, ArmStats, _derive_rng
from datasets import get_dataset
from ltr_evaluator import load_model, ModelMetadata

# Configuration
NUM_PEERS = 5
NUM_ROUNDS = 5
QUERIES_PER_ROUND = 100  # Each peer processes this many queries per round
BASE_PORT = 8090
PEER_DISCOVERY_WAIT = 3
# Wall-clock cadence: every peer emits one gossip tuple to one random
# stranger per interval. 5s = 720/hr = ~120k/wk per peer — natural rate
# control with no forwarding and no flooding.
GOSSIP_INTERVAL_S = 5.0
MIN_PULLS_FOR_ELIMINATION = 10  # Don't eliminate until arm has been tried this many times
ELIMINATION_THRESHOLD = 0.75  # Eliminate if reward < threshold * best_reward

# Master seed for deterministic runs. Default None → OS-entropy random (as
# before). Set to an int to get reproducible runs: every stochastic decision
# (query sampling, MAB draws, gossip neighbor choice, hotswap proposer, arm
# tiebreaking) is derived from this seed via per-(peer, purpose) tags, so
# each peer still runs an independent stream — only the overall trace is
# reproducible.
SEED: int | None = None

# Experiment config
DATASET_ID = "istella"  # Dataset to replay
DATA_DIR = Path(__file__).parent / "data"
MODELS_DIR = Path(__file__).parent / "models"
# Models pulled from peers via libtorrent land here rather than in MODELS_DIR,
# so it's obvious which files a peer authored locally vs. received over the
# wire. The directory is created on first use.
DOWNLOADS_DIR = Path(__file__).parent / "downloaded_models"
LOGS_DIR = Path(__file__).parent / "logs"

LOG_FILE = LOGS_DIR / f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(message: str) -> None:
    timestamp = datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "]"
    LOGS_DIR.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    print(message)


@dataclass
class GossipMessage(DataClassPayload[10]):
    """One peer's most-recent observation of one arm, plus discovery info.

    This is the *only* protocol message. Every gossip emission carries one
    such tuple, sent to one random stranger every ~5s. There is no
    forwarding by the receiver — spread is purely from each originator's
    own periodic emission. Lamport gates ordering so duplicates and
    out-of-order arrivals are no-ops.

    The discovery channel is collapsed onto a 20-byte BitTorrent info-hash:
    a receiver that doesn't yet have this arm reconstructs a magnet URI
    locally as `magnet:?xt=urn:btih:<hex>` and pulls the artifact. The
    `(host, port)` hint avoids a DHT round-trip for localhost transfers.
    `metadata_json` is kept inline so the receiver can write a sibling
    `meta.json` and load the model immediately on download.

    Each message is atomically signed by the originator's IPv8 keypair.
    `public_key` carries the wire-format public key bytes, `signature` is
    a digital signature over a canonical byte serialisation of every
    other field. Receivers verify (a) `sha1(public_key) == sender_key`
    so the sender_key cannot be forged, and (b) the signature is valid
    under that public key. Forged or unsigned messages are dropped.
    """
    sender_id: int           # IPv8 sender id (informational)
    sender_key: str          # hex(mid); receiver verifies sha1(public_key) matches
    arm_name: str
    pulls: int
    total_reward: float      # UCB1 evidence
    alpha: float             # Thompson evidence (1.0 if unused)
    beta: float              # Thompson evidence (1.0 if unused)
    lamport: int             # strictly increasing per (sender_key, arm)
    info_hash: bytes         # 20-byte BitTorrent info-hash (raw bytes)
    metadata_json: str       # sibling meta.json contents
    model_type: str
    host: str
    port: int
    public_key: bytes        # IPv8 public key in wire format
    signature: bytes         # signature over canonical serialisation of fields above


# Libtorrent listen-port range for each peer's seeder/leecher session.
# Ports are picked per-peer via a per-process-unique offset so multiple
# peers on the same host don't clash.
LT_PORT_MIN = 17000
LT_PORT_MAX = 17999
# How long a receiver waits (in seconds of polling) for a magnet download
# to complete before giving up on this round. Re-advertised arms retry
# naturally on subsequent ticks.
LT_DOWNLOAD_TIMEOUT_S = 60.0


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


def _find_model_file_by_name(model_name: str) -> Path | None:
    """Locate a model file on disk by its metadata `name` field.

    Filenames vary by type (.txt, .json, .npy), but every model has a
    sibling `<file>.meta.json` whose `name` field matches what the bandit
    tracks. We scan meta files once per call — fine at hot-swap rates.

    Scans both MODELS_DIR (built-ins + locally proposed) and DOWNLOADS_DIR
    (arms received via torrent from other peers).
    """
    for search_dir in (MODELS_DIR, DOWNLOADS_DIR):
        if not search_dir.exists():
            continue
        for meta_file in search_dir.glob("*.meta.json"):
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
            except Exception:
                continue
            if meta.get("name") == model_name:
                model_file = Path(str(meta_file).replace(".meta.json", ""))
                if model_file.exists():
                    return model_file
    return None


def _write_meta_and_load(
    model_path: Path,
    metadata_json: str,
):
    """Write the sibling `.meta.json` and load the model. Runs in an executor."""
    meta_path = model_path.with_suffix(model_path.suffix + ".meta.json")
    meta_path.write_text(metadata_json)
    model, _meta = load_model(model_path)
    return model


# ----------------------------------------------------------- gossip signing
#
# Each GossipMessage is atomically signed with the originator's IPv8
# keypair. The serialised byte string used for signing covers every field
# in the message except `public_key` and `signature` themselves, in a
# fixed order with length-prefixed encoding so neither sender nor receiver
# can disagree on what was signed. We deliberately don't trust the IPv8
# transport-level encoding for this — building the canonical form here
# means we control the binding precisely.

_GOSSIP_DOMAIN = b"LTR-MAB-gossip-v1\x00"


def _pack_bytes(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


def _pack_str(s: str) -> bytes:
    return _pack_bytes(s.encode("utf-8"))


def _gossip_canonical_bytes(
    sender_id: int,
    sender_key: str,
    arm_name: str,
    pulls: int,
    total_reward: float,
    alpha: float,
    beta: float,
    lamport: int,
    info_hash: bytes,
    metadata_json: str,
    model_type: str,
    host: str,
    port: int,
) -> bytes:
    """Deterministic byte representation of a gossip payload for signing."""
    return (
        _GOSSIP_DOMAIN
        + struct.pack(">q", int(sender_id))
        + _pack_str(sender_key)
        + _pack_str(arm_name)
        + struct.pack(">q", int(pulls))
        + struct.pack(">d", float(total_reward))
        + struct.pack(">d", float(alpha))
        + struct.pack(">d", float(beta))
        + struct.pack(">q", int(lamport))
        + _pack_bytes(info_hash)
        + _pack_str(metadata_json)
        + _pack_str(model_type)
        + _pack_str(host)
        + struct.pack(">i", int(port))
    )


class TorrentSeeder:
    """One libtorrent session per peer. Seeds local models and downloads
    magnets received via gossip advertisements.

    Designed for localhost-first: no tracker, no DHT bootstrap. The gossip
    payload carries the sender's libtorrent `(host, port)` so the receiver
    can `handle.connect_peer(...)` immediately after adding the magnet.
    """

    def __init__(self, peer_id: int) -> None:
        if lt is None:
            raise RuntimeError("libtorrent is not installed")
        self._peer_id = peer_id
        self._session = lt.session()
        # Per-peer port so co-located peers don't collide. The mod keeps it
        # bounded; collisions between distinct processes are rare enough
        # and libtorrent picks the next free port if occupied.
        port = LT_PORT_MIN + (os.getpid() % (LT_PORT_MAX - LT_PORT_MIN))
        try:
            self._session.listen_on(port, port + 20)
        except Exception:
            self._session.listen_on(LT_PORT_MIN, LT_PORT_MAX)

        settings = self._session.get_settings()
        # Keep DHT + LSD on so non-localhost scenarios still work, but
        # don't rely on them in the happy path.
        settings["enable_dht"] = True
        settings["enable_lsd"] = True
        # Allow peers on the same LAN / loopback to connect.
        settings["allow_multiple_connections_per_ip"] = True
        self._session.apply_settings(settings)

        # arm_name -> handle (seed) kept alive for the duration of the run.
        self._seed_handles: dict[str, Any] = {}
        # arm_name -> magnet URI we published (used internally for our own
        # session bookkeeping; not transmitted on the wire — peers receive
        # only the 20-byte info-hash and reconstruct the magnet themselves).
        self._magnets: dict[str, str] = {}
        # arm_name -> raw 20-byte info-hash, the on-wire identifier.
        self._info_hashes: dict[str, bytes] = {}

    # ----------------------------------------------------------- seed

    def seed_model(self, arm_name: str, model_path: Path) -> bytes | None:
        """Create a .torrent for `model_path`, add it as a seed, return the
        20-byte info-hash. Idempotent per arm_name.

        We track the magnet URI internally for our own session, but only
        the info-hash is exposed to callers — that's what rides the gossip
        wire. Receivers reconstruct the magnet locally.
        """
        if arm_name in self._info_hashes:
            return self._info_hashes[arm_name]

        try:
            torrent_path = Path(str(model_path) + ".torrent")
            if not torrent_path.exists():
                fs = lt.file_storage()
                lt.add_files(fs, str(model_path))
                t = lt.create_torrent(fs)
                t.set_creator("LTR-MAB seeder")
                lt.set_piece_hashes(t, str(model_path.parent))
                torrent_path.write_bytes(lt.bencode(t.generate()))

            info = lt.torrent_info(str(torrent_path))
            handle = self._session.add_torrent({
                "ti": info,
                "save_path": str(model_path.parent),
            })
            # Ensure we're in seed-only mode for files already complete.
            handle.flags = handle.flags  # no-op; keeping libtorrent happy
            magnet = lt.make_magnet_uri(info)
            ih_obj = info.info_hash()
            # libtorrent's sha1_hash exposes raw bytes via to_bytes().
            try:
                info_hash = bytes(ih_obj.to_bytes())
            except AttributeError:
                # Older libtorrent: fall back to parsing the hex string.
                info_hash = bytes.fromhex(str(ih_obj))
            self._seed_handles[arm_name] = handle
            self._magnets[arm_name] = magnet
            self._info_hashes[arm_name] = info_hash
            log(f"[Peer {self._peer_id}] SEEDING {arm_name} info_hash={info_hash.hex()}")
            return info_hash
        except Exception as exc:
            log(f"[Peer {self._peer_id}] seed_model({arm_name}) failed: {exc}")
            return None

    def magnet_for(self, arm_name: str) -> str | None:
        return self._magnets.get(arm_name)

    def info_hash_for(self, arm_name: str) -> bytes | None:
        return self._info_hashes.get(arm_name)

    @staticmethod
    def magnet_from_info_hash(info_hash: bytes) -> str:
        """Reconstruct a BitTorrent magnet URI from a 20-byte info-hash."""
        return f"magnet:?xt=urn:btih:{info_hash.hex()}"

    def listen_endpoint(self) -> tuple[str, int]:
        """Return the (host, port) other peers should use in connect_peer.

        We always advertise 127.0.0.1 because the pull-based design
        currently only exercises localhost-to-localhost transfers; DHT
        handles WAN discovery for the rare non-local case.
        """
        port = self._session.listen_port()
        return ("127.0.0.1", int(port))

    # --------------------------------------------------------- download

    async def download(
        self,
        magnet: str,
        save_dir: Path,
        extra_peer: tuple[str, int] | None,
        timeout_s: float = LT_DOWNLOAD_TIMEOUT_S,
    ) -> Path | None:
        """Download `magnet` into `save_dir`; return the resulting file path.

        If `extra_peer` is given, it's connected explicitly so localhost
        transfers complete without waiting on DHT / tracker.
        """
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            params = lt.parse_magnet_uri(magnet)
        except Exception as exc:
            log(f"[Peer {self._peer_id}] bad magnet: {exc}")
            return None
        params.save_path = str(save_dir)
        try:
            handle = self._session.add_torrent(params)
        except Exception as exc:
            log(f"[Peer {self._peer_id}] add_torrent failed: {exc}")
            return None

        if extra_peer is not None:
            try:
                handle.connect_peer(extra_peer)
            except Exception as exc:
                log(f"[Peer {self._peer_id}] connect_peer({extra_peer}) failed: {exc}")

        deadline = asyncio.get_event_loop().time() + timeout_s
        metadata_ready = False
        while asyncio.get_event_loop().time() < deadline:
            status = handle.status()
            if not metadata_ready and status.has_metadata:
                metadata_ready = True
                # Once metadata is in, try re-seeding the connect_peer hint
                # in case the first attempt raced metadata arrival.
                if extra_peer is not None:
                    try:
                        handle.connect_peer(extra_peer)
                    except Exception:
                        pass
            if status.is_seeding or status.progress >= 1.0:
                # Find the saved file. Single-file torrent → info name.
                ti = handle.torrent_file()
                if ti is None:
                    await asyncio.sleep(0.2)
                    continue
                files = ti.files()
                rel = files.file_path(0)
                return save_dir / rel
            await asyncio.sleep(0.3)

        log(f"[Peer {self._peer_id}] download timed out for {magnet[:60]}…")
        try:
            self._session.remove_torrent(handle)
        except Exception:
            pass
        return None

    def shutdown(self) -> None:
        try:
            for handle in list(self._seed_handles.values()):
                try:
                    self._session.remove_torrent(handle)
                except Exception:
                    pass
            self._seed_handles.clear()
            self._magnets.clear()
            self._session = None
        except Exception:
            pass


class LTRMABCommunity(Community):
    """Community for LTR model selection via MAB with real models."""
    community_id = os.urandom(20)
    _peer_counter = 0
    _state = None  # Shared state

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)
        self.add_message_handler(GossipMessage, self.on_gossip)

        # Model names heard about via gossip advertisements but whose
        # torrent we're still downloading. Held out of the bandit until
        # the file lands so the MAB doesn't try to score an arm whose
        # predictions we can't compute.
        self._announced_models: set[str] = set()
        # Per-model state of in-flight downloads so duplicate
        # advertisements from multiple peers don't start parallel downloads.
        self._downloading: set[str] = set()

        # Assign peer ID
        LTRMABCommunity._peer_counter += 1
        self.peer_id = LTRMABCommunity._peer_counter

        # Libtorrent seeder/leecher for model artefact transfer.
        self.seeder = TorrentSeeder(self.peer_id)
        # Cached ad entries for arms we're currently seeding — rebuilt
        # from self.seeder each gossip cycle.
        self._my_advertisements: dict[str, dict] = {}

        # Initialize MAB with initial models (excludes hot-swap model)
        model_names = list(self._state["initial_model_names"])
        algorithm = self._state.get("algorithm", "ucb1")
        peer_id = str(self.peer_id)
        seed = self._state.get("seed", SEED)
        # Per-peer RNG for gossip neighbor selection. Each peer gets its own
        # independent stream so two peers picking neighbors in the same tick
        # don't consume from the same draw sequence.
        self._rng = _derive_rng(seed, peer_id, "community")
        if algorithm == "thompson":
            self.bandit = ThompsonSampling(model_names, peer_id=peer_id, seed=seed)
        else:
            self.bandit = UCB1(model_names, c=2.0, peer_id=peer_id, seed=seed)
        # Cached Lamport stable identity used in outgoing gossip and
        # accepted by receivers as the gating key. Falls back to peer_id
        # before IPv8 has assigned `my_peer.mid`.
        self._stable_key = peer_id
        self.active_models = set(model_names)
        self.excluded_models = set()

        # Metric label
        self.metric = self._state.get("metric", "ndcg")

        # Optional callback for GUI event logging: fn(msg: str, kind: str)
        self.on_event = None

        # Tracking
        self.queries_processed = 0
        self.cumulative_scores = {1: 0.0, 5: 0.0, 10: 0.0}
        self.round_scores = {1: 0.0, 5: 0.0, 10: 0.0}
        self.round_queries = 0

        # Seed every model we already have on disk. Their magnets will
        # ride the first GossipMessage that picks them on rotation.
        for name in model_names:
            self._seed_existing_model(name)

    @classmethod
    def set_state(cls, state: dict):
        cls._state = state

    def started(self) -> None:
        log(f"[Peer {self.peer_id}] Started with models: {list(self.active_models)}")

    def select_active_arm(self) -> str | None:
        """Select arm only from active (non-excluded) models."""
        if not self.active_models:
            return None
        return self.bandit.select_arm(active=self.active_models)

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

    def _seed_existing_model(self, arm_name: str, lookup_name: str | None = None) -> None:
        """Find the on-disk file for `lookup_name` (defaults to `arm_name`),
        seed it via libtorrent, cache its ad under `arm_name`. The advertised
        metadata's `name` field is rewritten to `arm_name` so receivers store
        and key everything under the unique name.
        """
        search_name = lookup_name or arm_name
        model_path = _find_model_file_by_name(search_name)
        if model_path is None:
            log(f"[Peer {self.peer_id}] seed: no on-disk file for arm '{search_name}' (scanned {MODELS_DIR})")
            return
        info_hash = self.seeder.seed_model(arm_name, model_path)
        if not info_hash:
            log(f"[Peer {self.peer_id}] seed: seeder returned no info-hash for {arm_name} ({model_path})")
            return
        try:
            metadata = ModelMetadata.load(model_path)
            meta_dict = dict(metadata.__dict__)
            meta_dict["name"] = arm_name
            metadata_json = json.dumps(meta_dict)
        except Exception as exc:
            log(f"[Peer {self.peer_id}] seed: missing/unreadable meta for {search_name}: {exc}")
            return
        host, port = self.seeder.listen_endpoint()
        self._my_advertisements[arm_name] = {
            "info_hash": info_hash,
            "model_type": metadata.type,
            "metadata_json": metadata_json,
            "host": host,
            "port": port,
        }
        log(f"[Peer {self.peer_id}] seed: advertised {arm_name} (info_hash={info_hash.hex()[:16]}…, endpoint={host}:{port})")

    def _stable_self_key(self) -> str:
        """Stable per-peer identifier used in outgoing gossip and as the
        Lamport gating key on receivers. We prefer IPv8's `my_peer.mid` —
        a cryptographic identity that survives across community
        reinitialisation within the same on-disk keyfile — falling back to
        the in-process peer_id before IPv8 has finished setting up."""
        try:
            return self.my_peer.mid.hex()
        except Exception:
            return str(self.peer_id)

    def _verify_gossip_signature(self, payload: GossipMessage) -> bool:
        """Reject any message that isn't atomically signed by its claimed
        originator. Three checks must all pass:

        1. The public key in the message must hash (SHA1) to the claimed
           `sender_key`. This pins the sender_key to a real keypair —
           a forger can't pick an arbitrary mid because they don't have
           the corresponding private key.
        2. `default_eccrypto` must accept the public key bytes (i.e. they
           parse as a valid IPv8 public key).
        3. The signature must verify against the canonical byte
           serialisation of every other field. Tampering with any field
           in transit invalidates this.
        """
        pk_bin = payload.public_key
        sig = payload.signature
        if not pk_bin or not sig:
            log(f"[Peer {self.peer_id}] DROPPED unsigned gossip from {payload.sender_key[:8]}")
            return False

        # Sender key must be the SHA1 mid of the public key.
        try:
            claimed_mid = bytes.fromhex(payload.sender_key)
        except ValueError:
            log(f"[Peer {self.peer_id}] DROPPED gossip with non-hex sender_key")
            return False
        if hashlib.sha1(pk_bin).digest() != claimed_mid:
            log(f"[Peer {self.peer_id}] DROPPED gossip: sender_key/public_key mismatch")
            return False

        try:
            public_key = default_eccrypto.key_from_public_bin(pk_bin)
        except Exception as exc:
            log(f"[Peer {self.peer_id}] DROPPED gossip: bad public key: {exc}")
            return False

        canonical = _gossip_canonical_bytes(
            sender_id=int(payload.sender_id),
            sender_key=payload.sender_key,
            arm_name=payload.arm_name,
            pulls=int(payload.pulls),
            total_reward=float(payload.total_reward),
            alpha=float(payload.alpha),
            beta=float(payload.beta),
            lamport=int(payload.lamport),
            info_hash=payload.info_hash,
            metadata_json=payload.metadata_json,
            model_type=payload.model_type,
            host=payload.host,
            port=int(payload.port),
        )
        # IPv8's verify(...) returns the recovered message on success and
        # raises on failure (libnacl-style) for some key types; M2Crypto
        # returns a bool. Treat any exception as invalid; treat an
        # explicit False as invalid; otherwise consider it a pass.
        try:
            verdict = public_key.verify(sig, canonical)
        except Exception as exc:
            log(f"[Peer {self.peer_id}] DROPPED gossip: signature verify error: {exc}")
            return False
        if verdict is False:
            log(f"[Peer {self.peer_id}] DROPPED gossip: invalid signature from {payload.sender_key[:8]}")
            return False
        return True

    def _pick_gossip_arm(self) -> str | None:
        """Pick one random arm this peer is currently using.

        Defensive dissemination: each emission advertises *one* arm the
        sender uses — we don't push other peers' evidence on their behalf.
        The arm choice rotates across the active set so every model gets
        coverage over time without any single message carrying bulk state.
        """
        active = sorted(self.active_models)
        if not active:
            return None
        idx = int(self._rng.integers(len(active)))
        return active[idx]

    def _pick_random_stranger(self) -> "Peer | None":
        """Ask IPv8 for a peer we can talk to right now.

        IPv8's RandomWalk strategy continuously churns the peer table, so
        sampling one entry per gossip emission gives us a fresh stranger
        on each cycle without us having to manage walks ourselves. Returns
        None if no peers are connected yet.
        """
        peers = self.get_peers()
        if not peers:
            return None
        idx = int(self._rng.integers(len(peers)))
        return peers[idx]

    async def send_gossip(self) -> int:
        """Emit one tuple to one random stranger.

        Per the defensive-dissemination model: no fan-out, no waves, no
        forwarding by receivers. The next 5-second cycle will pick a
        different arm and a different stranger, and so on. Long-run
        coverage is guaranteed by the random walk + repetition; short-run
        latency to any specific neighbour is amortised across cycles.
        """
        arm = self._pick_gossip_arm()
        if arm is None:
            return 0
        target = self._pick_random_stranger()
        if target is None:
            return 0

        ad = self._my_advertisements.get(arm, {})
        own = self.bandit.own_observation(arm)
        if own is None:
            return 0
        # Ensure our outgoing Lamport is monotonically ahead of whatever
        # the bandit last stamped for self-updates.
        lamport = self.bandit.next_lamport()

        sender_key = self._stable_self_key()
        info_hash = ad.get("info_hash", b"")
        metadata_json = ad.get("metadata_json", "")
        model_type = ad.get("model_type", "")
        host = ad.get("host", "")
        port = int(ad.get("port", 0))

        # Build the canonical byte string for signing — must be byte-for-byte
        # reproducible on the receiver so the signature verifies.
        canonical = _gossip_canonical_bytes(
            sender_id=self.peer_id,
            sender_key=sender_key,
            arm_name=arm,
            pulls=int(own.pulls),
            total_reward=float(own.total_reward),
            alpha=float(own.alpha),
            beta=float(own.beta),
            lamport=int(lamport),
            info_hash=info_hash,
            metadata_json=metadata_json,
            model_type=model_type,
            host=host,
            port=port,
        )
        public_key_bin = self.my_peer.public_key.key_to_bin()
        signature = self.my_peer.key.signature(canonical)

        msg = GossipMessage(
            sender_id=self.peer_id,
            sender_key=sender_key,
            arm_name=arm,
            pulls=int(own.pulls),
            total_reward=float(own.total_reward),
            alpha=float(own.alpha),
            beta=float(own.beta),
            lamport=int(lamport),
            info_hash=info_hash,
            metadata_json=metadata_json,
            model_type=model_type,
            host=host,
            port=port,
            public_key=public_key_bin,
            signature=signature,
        )
        self.ez_send(target, msg)
        return 1

    @lazy_wrapper(GossipMessage)
    def on_gossip(self, peer: Peer, payload: GossipMessage) -> None:
        """Single message handler for everything: stats + discovery.

        Atomic verification first: every accepted message must carry a
        valid signature from a public key whose `sha1` digest matches the
        claimed `sender_key` (the IPv8 mid). This prevents impersonation
        — a peer cannot forge gossip from someone else, and cannot tamper
        with any field in transit without the signature failing.

        Statistics: gated by Lamport per (sender_key, arm) — strictly
        increasing replaces, anything else dropped.

        Discovery: if the arm is unknown locally and the message carries a
        magnet, kick off a libtorrent download. Once the file lands and is
        scored, the arm enters `bandit.own` and subsequent gossips for it
        contribute to the aggregate.

        We never re-emit. Spread happens because the originator keeps
        gossiping the same tuple to fresh strangers every interval.
        """
        arm = payload.arm_name
        if not arm:
            return

        if not self._verify_gossip_signature(payload):
            return

        if arm in self.bandit.own:
            accepted = self.bandit.apply_gossip(
                arm=arm,
                sender=payload.sender_key,
                pulls=int(payload.pulls),
                total_reward=float(payload.total_reward),
                alpha=float(payload.alpha),
                beta=float(payload.beta),
                lamport=int(payload.lamport),
            )
            if accepted:
                log(
                    f"[Peer {self.peer_id}] GOSSIP from {payload.sender_key[:8]}: "
                    f"{arm} pulls={payload.pulls} reward={payload.total_reward:.3f} "
                    f"L={payload.lamport}"
                )
            return

        # Arm unknown locally. Kick off discovery via libtorrent if the
        # advertisement is usable; otherwise drop and wait for a peer that
        # also seeds this arm to gossip it later. The wire carries only a
        # 20-byte info-hash; we reconstruct the magnet URI on this side.
        if not payload.info_hash or len(payload.info_hash) != 20:
            return
        if arm in self._downloading:
            return

        magnet = TorrentSeeder.magnet_from_info_hash(payload.info_hash)
        ad = {
            "magnet": magnet,
            "metadata_json": payload.metadata_json,
            "model_type": payload.model_type,
            "host": payload.host,
            "port": int(payload.port),
        }
        self._announced_models.add(arm)
        self._start_download_if_idle(arm, ad, payload.sender_id)

    def _start_download_if_idle(self, arm_name: str, ad: dict, sender_id: int) -> None:
        """Dispatch a torrent download for `arm_name` unless one is already running.

        Short-circuit: if the proposed arm shares an underlying base model
        with something we already have locally (e.g. the proposing peer
        sent `lightgbm@abcd1234` and we've got the initial `lightgbm` on
        disk), libtorrent would refuse the magnet as a duplicate info-hash.
        We instead alias to the base's pre-computed scores and register
        the arm in-process, skipping the network round-trip entirely.
        """
        if arm_name in self.bandit.own:
            self._announced_models.discard(arm_name)
            return
        if arm_name in self._downloading:
            return

        if self._try_alias_to_local_base(arm_name, sender_id):
            self._announced_models.discard(arm_name)
            return

        self._downloading.add(arm_name)

        magnet = ad["magnet"]
        metadata_json = ad.get("metadata_json", "{}")
        model_type = ad.get("model_type", "")
        host = ad.get("host")
        port = ad.get("port")
        extra_peer = (host, int(port)) if host and port else None

        if self.on_event:
            self.on_event(
                f"Downloading model {arm_name} from Peer {sender_id}…",
                "info",
            )

        loop = asyncio.get_event_loop()
        loop.create_task(self._download_and_materialize(
            arm_name, magnet, metadata_json, model_type, extra_peer, sender_id,
            save_dir=DOWNLOADS_DIR,
        ))

    def _try_alias_to_local_base(self, unique_name: str, sender_id: int) -> bool:
        """If `unique_name` is `<base>@<hex>` and we already have `<base>`
        locally (with precomputed scores), register the unique arm by
        aliasing to the base's model + scores. Returns True on success.

        This handles the common case where two peers were started from
        the same set of initial models on disk: they don't need to
        re-fetch each other's identical artifacts via libtorrent (which
        would fail due to colliding magnet info-hashes anyway).

        Suppressed when the experiment sets `state["disable_alias"] = True`.
        Useful for hot-swap experiments where the alias shortcut would
        make discovery latency artificially zero — receivers should
        actually take the libtorrent path so the gossip protocol's
        propagation cadence shows up in the measured discovery round.
        """
        state = self._state
        if state.get("disable_alias", False):
            return False
        if "@" not in unique_name:
            return False
        base = unique_name.rsplit("@", 1)[0]
        scores_map = state.get("model_scores", {})
        models_map = state.get("models", {})
        if base not in scores_map or base not in models_map:
            return False
        scores_map[unique_name] = scores_map[base]
        models_map[unique_name] = models_map[base]
        # Now `add_model` will succeed since precomputed scores exist.
        self.add_model(unique_name)
        if self.on_event:
            self.on_event(
                f"NEW ARM aliased from local base '{base}' (announced by "
                f"Peer {sender_id}): {unique_name}",
                "round",
            )
        log(
            f"[Peer {self.peer_id}] ALIASED {unique_name} -> local base "
            f"'{base}' (skipped libtorrent; both refer to identical artifact)"
        )
        return True

    def _get_mean_reward(self, stats_entry: dict) -> float:
        """Get mean/expected reward from stats, works with both UCB1 and Thompson."""
        return stats_entry.get("mean_reward", stats_entry.get("expected_reward", 0.0))

    def check_exclusions(self, round_num: int) -> list[str]:
        """Eliminate arms whose UCB is below the LCB of the best arm (Insert-Eliminate style).

        An arm is retired only when confidence intervals are non-overlapping:
          UCB(k) < LCB(best)
        This gives a formal guarantee that no near-optimal arm is eliminated.
        Reference: Chawla et al. (2020), Gossiping Insert-Eliminate.
        """
        if len(self.active_models) <= 1:
            return []

        # Require minimum evidence before any arm is eligible. Pulls are
        # aggregated across own + non-stale peer observations.
        active_with_pulls = {
            name for name in self.active_models
            if self.bandit._aggregate_pulls(name) >= MIN_PULLS_FOR_ELIMINATION
        }
        if len(active_with_pulls) <= 1:
            return []

        # Find arm with highest LCB — this is the "best" arm by conservative estimate
        best_name = max(active_with_pulls, key=lambda n: self.bandit.confidence_bounds(n)[0])
        best_lcb = self.bandit.confidence_bounds(best_name)[0]

        if best_lcb == 0.0:
            return []

        excluded = []
        for name in list(active_with_pulls):
            if name == best_name:
                continue
            arm_ucb = self.bandit.confidence_bounds(name)[1]
            if arm_ucb < best_lcb:
                lcb, ucb = self.bandit.confidence_bounds(name)
                self.exclude_model(name, round_num, best_name, best_lcb, lcb, ucb)
                excluded.append(name)

        return excluded

    def exclude_model(self, name: str, round_num: int, best_name: str, best_lcb: float, arm_lcb: float, arm_ucb: float) -> None:
        """Exclude a model from future selection."""
        if name not in self.active_models:
            return

        self.active_models.remove(name)
        self.excluded_models.add(name)

        log(f"")
        log(f"{'#'*70}")
        log(f"[Peer {self.peer_id}] ARM EXCLUDED: {name}")
        log(f"[Peer {self.peer_id}]   Round: {round_num}")
        log(f"[Peer {self.peer_id}]   Reason: UCB({name})={arm_ucb:.3f} < LCB({best_name})={best_lcb:.3f}  (CI=[{arm_lcb:.3f}, {arm_ucb:.3f}])")
        log(f"[Peer {self.peer_id}]   Remaining active: {list(self.active_models)}")
        log(f"{'#'*70}")
        log(f"")

    def add_model(self, model_name: str) -> None:
        """Hot-swap: add a newly-downloaded arm to this peer's MAB and seed it."""
        if model_name in self.bandit.own:
            log(f"[Peer {self.peer_id}] add_model({model_name}): already known, skipping")
            return
        state = self._state
        if model_name not in state["model_scores"]:
            log(f"[Peer {self.peer_id}] Cannot add {model_name}: no precomputed scores "
                f"(available: {sorted(state.get('model_scores', {}).keys())})")
            return

        self.bandit.add_arm(model_name)
        self.active_models.add(model_name)
        log(f"[Peer {self.peer_id}] HOT-SWAP: Added {model_name} to MAB")
        log(f"[Peer {self.peer_id}]   Active models: {sorted(self.active_models)}")

        # Seed the model file so downstream peers can pull it via torrent.
        self._seed_existing_model(model_name)

    async def propose_model(self, base_model_name: str) -> None:
        """Register a model locally under a unique, per-peer name and seed it.

        There is no immediate announcement: the regular gossip cycle picks
        this arm with the same probability as any other we use, so it
        propagates to a fresh stranger every interval until coverage is
        achieved. Random hex suffix guarantees uniqueness across peers and
        across re-proposals within one process."""
        rand_suffix = os.urandom(4).hex()
        unique_name = f"{base_model_name}@{rand_suffix}"

        state = self._state
        if unique_name not in state.get("model_scores", {}):
            if base_model_name not in state.get("model_scores", {}):
                log(f"[Peer {self.peer_id}] PROPOSE ABORTED: base model '{base_model_name}' "
                    f"has no precomputed scores; cannot register {unique_name}")
                return
            state["model_scores"][unique_name] = state["model_scores"][base_model_name]
            if "models" in state and base_model_name in state["models"]:
                state.setdefault("models", {})[unique_name] = state["models"][base_model_name]

        if unique_name in self.bandit.own:
            log(f"[Peer {self.peer_id}] PROPOSE skipped: {unique_name} already active")
            return

        self.bandit.add_arm(unique_name)
        self.active_models.add(unique_name)
        log(f"[Peer {self.peer_id}] HOT-SWAP: Added {unique_name} to MAB (base={base_model_name})")

        self._seed_existing_model(unique_name, lookup_name=base_model_name)
        if unique_name not in self._my_advertisements:
            await asyncio.sleep(0.1)
            self._seed_existing_model(unique_name, lookup_name=base_model_name)

        ad = self._my_advertisements.get(unique_name)
        if ad is None:
            log(f"[Peer {self.peer_id}] PROPOSE: no magnet for {unique_name} — peers will "
                f"discover it once seeding succeeds on a future gossip cycle")
            return
        log(f"[Peer {self.peer_id}] PROPOSED {unique_name} — will be advertised on next "
            f"gossip cycle")

    async def _download_and_materialize(
        self,
        model_name: str,
        magnet: str,
        metadata_json: str,
        model_type: str,
        extra_peer: tuple[str, int] | None,
        sender_id: int,
        save_dir: Path = MODELS_DIR,
    ) -> None:
        """Download the model file via libtorrent, then load + score + add_model."""
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            model_path = await self.seeder.download(magnet, save_dir, extra_peer)
            if model_path is None:
                log(f"[Peer {self.peer_id}] DOWNLOAD FAILED for {model_name} (timeout)")
                if self.on_event:
                    self.on_event(f"Failed to download {model_name}: timeout", "info")
                return

            loop = asyncio.get_event_loop()
            try:
                model = await loop.run_in_executor(
                    None,
                    _write_meta_and_load,
                    model_path, metadata_json,
                )
            except Exception as exc:
                log(f"[Peer {self.peer_id}] LOAD FAILED for {model_name}: {exc}")
                if self.on_event:
                    self.on_event(f"Failed to load {model_name}: {exc}", "info")
                return

            state = self._state
            if "X_test" not in state or "y_test" not in state:
                log(f"[Peer {self.peer_id}] shared state missing X_test/y_test; cannot score {model_name}")
                return

            try:
                scores = await loop.run_in_executor(
                    None,
                    precompute_model_scores,
                    {model_name: model},
                    state["X_test"],
                    state["y_test"],
                    state["query_boundaries"],
                    [1, 5, 10],
                    state.get("metric", "ndcg"),
                )
            except Exception as exc:
                log(f"[Peer {self.peer_id}] PRECOMPUTE FAILED for {model_name}: {exc}")
                if self.on_event:
                    self.on_event(f"Failed to score {model_name}: {exc}", "info")
                return

            state["models"][model_name] = model
            state["model_scores"][model_name] = scores[model_name]

            self.add_model(model_name)
            self._announced_models.discard(model_name)
            if self.on_event:
                self.on_event(
                    f"NEW ARM via torrent from Peer {sender_id}: {model_name}",
                    "round",
                )
        finally:
            self._downloading.discard(model_name)

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
    seed: int | None = None,
    disable_alias: bool = False,
) -> None:
    """Run local experiment with N peers and R rounds."""
    # Caller can override the module-level SEED for per-run reproducibility.
    if seed is None:
        seed = SEED
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
        "seed": seed,
        "disable_alias": disable_alias,
        # Needed by the torrent-download materialize path to score an arm
        # fetched from a peer. Without these, _download_and_materialize
        # bails at "shared state missing" and the arm never enters the
        # bandit (the alias shortcut sidesteps this, but real transfers
        # require it).
        "X_test": X_test,
        "y_test": y_test,
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

    # Query pool. One RNG per peer so seed 0 replays identical query streams;
    # the driver uses its own RNG for hot-swap proposer selection.
    total_queries = len(query_boundaries)
    per_peer_rngs: dict[int, np.random.Generator] = {}
    driver_rng = _derive_rng(seed, "driver", "hotswap")

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
            # One stable Generator per peer keyed by peer_id — reused across
            # rounds so the query sequence is deterministic given the seed.
            if comm.peer_id not in per_peer_rngs:
                per_peer_rngs[comm.peer_id] = _derive_rng(
                    seed, str(comm.peer_id), "queries"
                )
            peer_rng = per_peer_rngs[comm.peer_id]
            query_indices = peer_rng.choice(total_queries, size=queries_per_round, replace=replace)
            for query_idx in query_indices:
                comm.process_query(int(query_idx))

            log(f"[Peer {comm.peer_id}] Round {round_num} complete: {comm.get_round_summary()}")
            await sleep(0.01)  # let dashboard poll

        # Hot-swap: a random peer proposes XGBoost at the configured round
        if hotswap_round > 0 and round_num == hotswap_round and hotswap_model_name:
            proposer = communities[int(driver_rng.integers(len(communities)))]
            log(f"\n{'#'*70}")
            log(f"HOT-SWAP: Peer {proposer.peer_id} proposing {hotswap_model_name}")
            log(f"{'#'*70}")
            dashboard_state.event(f"HOT-SWAP: Peer {proposer.peer_id} proposing {hotswap_model_name}", "round")
            await proposer.propose_model(hotswap_model_name)
            await sleep(0.5)  # let announcement propagate

        # Gossip phase. Each peer emits one tuple to one random stranger;
        # we run several cycles per round here purely to compress simulated
        # wall-clock time (the live thread driver paces these to one per
        # GOSSIP_INTERVAL_S in real deployments).
        if gossip_enabled:
            dashboard_state.phase = "gossiping"
            log(f"\n--- Gossip Phase (Round {round_num}) ---")
            # One gossip per peer per round: each round corresponds 1:1 to a
            # GOSSIP_INTERVAL_S wall-clock tick in the live protocol. Each
            # peer picks one random own-arm and one random stranger.
            for comm in communities:
                sent = await comm.send_gossip()
                if sent:
                    log(f"[Peer {comm.peer_id}] gossiped one tuple to a random stranger")
                    dashboard_state.event(f"Peer {comm.peer_id} gossiped", "gossip")
            await sleep(0.1)
        else:
            log(f"\n--- Gossip Phase (Round {round_num}) --- SKIPPED (disabled)")
            dashboard_state.event("Gossip skipped (disabled)", "info")

        # Print arm stats after gossip
        log(f"\n--- Arm Statistics (after Round {round_num}) ---")
        for comm in communities:
            comm.print_arm_stats()

        # Survival check (exclusion phase)
        # Each peer reaches its own verdict from the gossiped CRDT evidence it
        # has merged so far. There is no exclusion broadcast — that would let
        # a single bad actor evict the strongest arm by simply announcing it
        # excluded. Agreement on which arm to drop comes from peers seeing the
        # same evidence, not from explicit exclusion messages.
        dashboard_state.phase = "survival"
        log(f"\n--- Survival Check (Round {round_num}) ---")
        all_excluded = set()
        for comm in communities:
            excluded = comm.check_exclusions(round_num)
            for model_name in excluded:
                if model_name not in all_excluded:
                    all_excluded.add(model_name)
                    lcb, ucb = comm.bandit.confidence_bounds(model_name)
                    reason = f"UCB={ucb:.3f} < best_LCB"
                    dashboard_state.event(f"ARM EXCLUDED: {model_name} ({reason})", "exclusion")
                    await sleep(0.1)

        if not all_excluded:
            log(f"[Round {round_num}] No models excluded this round")

        # Record round history for charts
        arm_pulls = {}  # arm -> total pulls across all peers
        arm_reward_sum = {}  # arm -> sum of mean_rewards across peers
        arm_reward_count = {}  # arm -> number of peers that have stats for this arm
        # Per-peer per-arm cumulative pulls for this round — used by Exp 3 to
        # measure when each specific peer first discovers a new arm.
        per_peer_pulls: dict[int, dict[str, int]] = {}
        total_cumulative_reward = 0.0
        total_queries_all = 0

        for comm in communities:
            stats = comm.bandit.get_stats()
            per_peer_pulls[comm.peer_id] = {
                name: int(s["pulls"]) for name, s in stats.items()
            }
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
            "per_peer_pulls": per_peer_pulls,
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
    parser.add_argument("--seed", type=int, default=None, help="Master RNG seed (None → module default SEED)")
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
        seed=args.seed,
    ))

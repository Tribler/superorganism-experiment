"""LTR Community Thread — runs a single IPv8 peer that joins the LTR MAB
community distributed across all current network peers.

Each running app instance is *one* peer.  When the user clicks RUN, this
peer starts its local query-loop, gossips statistics with whoever else is
on the network, and emits live snapshots of its *own* arms/rewards so the
GUI can display the local experiment status.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

_BENCH_DIR = Path(__file__).parent / "ltr-benchmarking"
if str(_BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCH_DIR))

# Shared file used by every running app instance to advertise its IPv8
# (host, port) so peers on the same machine can discover each other without
# depending on the public Dispersy bootstrap server (which is unreliable
# behind NAT, especially for two peers on the same host).
_PEER_REGISTRY_PATH = _BENCH_DIR / ".peer_registry.json"

# Registry entries older than this are treated as dead (process crashed before
# cleanup). Live peers heartbeat by rewriting their own entry periodically.
_REGISTRY_STALE_SECONDS = 30
_REGISTRY_HEARTBEAT_SECONDS = 5


def _read_peer_registry() -> dict:
    """Load registry and drop entries whose heartbeat timestamp is stale.

    Format: { pid: [host, port, ts] }. Legacy entries ([host, port]) are
    treated as stale and dropped.
    """
    try:
        raw = json.loads(_PEER_REGISTRY_PATH.read_text())
    except Exception:
        return {}
    now = time.time()
    fresh: dict = {}
    for pid, entry in raw.items():
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        ts = entry[2]
        if not isinstance(ts, (int, float)):
            continue
        if now - ts > _REGISTRY_STALE_SECONDS:
            continue
        fresh[pid] = entry
    return fresh


def _write_peer_registry(registry: dict) -> None:
    try:
        _PEER_REGISTRY_PATH.write_text(json.dumps(registry))
    except Exception:
        pass


def _register_self(pid: str, host: str, port: int) -> dict:
    """Prune stale entries, register this peer with a current timestamp, and
    return the pruned registry snapshot (excluding self) so the caller can
    walk to any currently-live peers.
    """
    registry = _read_peer_registry()
    registry[pid] = [host, port, time.time()]
    _write_peer_registry(registry)
    return {p: e for p, e in registry.items() if p != pid}


# ---------------------------------------------------------------------------
# Local-peer GUI state  (mirrors _GUIState from ltr_thread.py but single-peer)
# ---------------------------------------------------------------------------

class _LocalPeerState:
    """Tracks the state of *this* peer and emits GUI snapshots."""

    def __init__(self, snapshot_signal: Signal, log_signal: Signal):
        self._snap_sig = snapshot_signal
        self._log_sig = log_signal

        self.community = None          # LTRMABCommunity instance for this peer
        self.current_round = 0
        self.phase = "idle"
        self.config: dict = {}
        self.oracle: dict = {}
        self.round_history: list = []
        self.t0 = time.time()

    # ------------------------------------------------------------------ events

    def event(self, msg: str, kind: str = "info") -> None:
        entry = {"t": round(time.time() - self.t0, 2), "kind": kind, "msg": msg}
        self._log_sig.emit(entry)
        self._emit_snapshot()

    def _emit_snapshot(self) -> None:
        self._snap_sig.emit(self._build_snapshot())

    def _build_snapshot(self) -> dict:
        peer_data = self._peer_data()
        return {
            "round": self.current_round,
            "phase": self.phase,
            "config": self.config,
            "oracle": self.oracle,
            "elapsed": round(time.time() - self.t0, 1),
            "peer": peer_data,
            "round_history": list(self.round_history),
            "network_peers": self._network_peer_count(),
        }

    def _peer_data(self) -> dict:
        c = self.community
        if c is None:
            return {}
        stats = c.bandit.get_stats()
        q = max(c.queries_processed, 1)
        return {
            "id": c.peer_id,
            "queries": c.queries_processed,
            "active": sorted(c.active_models),
            "excluded": sorted(c.excluded_models),
            "best": c.bandit.get_best_arm() if c.bandit.total_pulls > 0 else None,
            "scores": {str(k): round(v / q, 4) for k, v in c.cumulative_scores.items()},
            "arms": {
                name: {
                    "pulls": s["pulls"],
                    "reward": round(c._get_mean_reward(s), 4),
                    "status": "excluded" if name in c.excluded_models else "active",
                }
                for name, s in stats.items()
            },
        }

    def _network_peer_count(self) -> int:
        if self.community is None:
            return 0
        return len(self.community.get_peers())

    # ------------------------------------------------------------------ hooks

    class _HookedList(list):
        def __init__(self, owner: "_LocalPeerState"):
            super().__init__()
            self._owner = owner

        def append(self, item):
            super().append(item)
            self._owner._emit_snapshot()

    def install_hooked_list(self) -> None:
        self.round_history = self._HookedList(self)


# ---------------------------------------------------------------------------
# QThread
# ---------------------------------------------------------------------------

class LTRCommunityThread(QThread):
    """Runs a single LTR MAB IPv8 peer in a background thread.

    The peer joins whatever other peers are on the network (same bootstrap),
    runs the bandit query loop, gossiping between rounds, and emits live
    snapshots of the *local* peer's state only.

    Signals (Thread → GUI):
        started_ok()          models loaded, peer up, about to start rounds
        snapshot(dict)        local-peer snapshot after every event / round
        log_event(dict)       single log entry {t, kind, msg}
        finished_ok()         all rounds done
        error(str)            fatal error
    """

    started_ok  = Signal()
    snapshot    = Signal(dict)
    log_event   = Signal(dict)
    finished_ok = Signal()
    error       = Signal(str)

    COMMUNITY_ID = b"superorg-ltr-exp-v1\x00"  # 20 bytes

    def __init__(
        self,
        dataset_id: str,
        algorithm: str,
        metric: str = "ndcg",
        queries_per_round: int = 100,
        gossip_enabled: bool = True,
        hotswap_round: int = 0,
        hotswap_model: str = "",
        peer_port: int = 0,          # 0 → pick a free port
        key_path: Optional[str] = None,
        bootstrap_addresses: Optional[list[tuple[str, int]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.dataset_id        = dataset_id
        self.algorithm         = algorithm
        self.metric            = metric
        # `queries_per_round` sets the tick size: queries processed between
        # each gossip + exclusion check + snapshot. `hotswap_round` triggers
        # a one-shot model proposal at that tick (0 = disabled).
        self.queries_per_round = queries_per_round
        self.gossip_enabled    = gossip_enabled
        self.hotswap_round     = hotswap_round
        # Name of the arm to propose at hot-swap time. Empty string falls
        # back to auto-detecting an xgboost model (legacy behaviour).
        self.hotswap_model     = hotswap_model
        self.peer_port         = peer_port
        self.key_path          = key_path or str(
            _BENCH_DIR / f"peer_community_{os.getpid()}.pem"
        )

        self.bootstrap_addresses = bootstrap_addresses or []

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------ QThread

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._loop.close()

    def stop(self) -> None:
        if self._loop and not self._loop.is_closed() and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    # ------------------------------------------------------------------ async core

    async def _run(self) -> None:
        self._stop_event = asyncio.Event()

        import numpy as np
        import local_experiment as exp
        from local_experiment import (
            LTRMABCommunity,
            BASE_PORT,
            GOSSIP_INTERVAL_S,
            PEER_DISCOVERY_WAIT,
            SEED,
        )
        from mab import _derive_rng
        from ipv8.configuration import (
            ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs,
        )
        from ipv8_service import IPv8
        from datasets import get_dataset

        state = _LocalPeerState(self.snapshot, self.log_event)
        state.install_hooked_list()

        # ── Load dataset ──────────────────────────────────────────────────
        state.event(f"Loading dataset '{self.dataset_id}'…", "info")
        dataset = get_dataset(self.dataset_id, _BENCH_DIR / "data")
        X_test, y_test, _, groups = dataset.load_test()
        query_boundaries: list[tuple[int, int]] = []
        start = 0
        for g in groups:
            query_boundaries.append((start, start + g))
            start += g

        # ── Load models ───────────────────────────────────────────────────
        state.event("Loading models…", "info")
        models = exp.load_experiment_models(self.dataset_id)

        if not models:
            self.error.emit("No models found for dataset " + self.dataset_id)
            return

        # ── Precompute scores ─────────────────────────────────────────────
        state.event("Precomputing model scores…", "info")
        model_scores = exp.precompute_model_scores(
            models, X_test, y_test, query_boundaries,
            k_values=[1, 5, 10], metric=self.metric,
        )
        oracle = {
            name: round(
                sum(model_scores[name][10]) / max(len(model_scores[name][10]), 1), 4
            )
            for name in models
        }

        hotswap_model_name = None
        if self.hotswap_round > 0:
            if self.hotswap_model and self.hotswap_model in models:
                hotswap_model_name = self.hotswap_model
            elif self.hotswap_model:
                state.event(
                    f"Hot-swap model '{self.hotswap_model}' not found in loaded "
                    f"models; hot-swap disabled for this peer.",
                    "info",
                )
            else:
                # Legacy fallback: pick an xgboost variant if present.
                for name in models:
                    if "xgboost" in name.lower() or "xgb" in name.lower():
                        hotswap_model_name = name
                        break

        initial_model_names = [
            n for n in models
            if n != hotswap_model_name
            and "xgboost" not in n.lower()
            and "xgb" not in n.lower()
        ]

        # ── Shared community state ────────────────────────────────────────
        shared = {
            "models": models,
            "initial_model_names": initial_model_names,
            "model_scores": model_scores,
            "query_boundaries": query_boundaries,
            "num_queries": len(query_boundaries),
            "algorithm": self.algorithm,
            "metric": self.metric,
            # Kept around so models received via P2P transfer can be scored
            # against the same test set without re-loading the dataset.
            "X_test": X_test,
            "y_test": y_test,
        }
        LTRMABCommunity.set_state(shared)
        LTRMABCommunity._peer_counter = 0

      
        LTRMABCommunity.community_id = LTRCommunityThread.COMMUNITY_ID
        port = self.peer_port if self.peer_port else (BASE_PORT + os.getpid() % 1000)

        state.config = {
            "dataset": self.dataset_id,
            "algorithm": self.algorithm,
            "metric": self.metric,
            # num_rounds is unbounded in continuous mode; 0 signals "∞" to UI.
            "num_rounds": 0,
            "queries_per_round": self.queries_per_round,
            "gossip_enabled": self.gossip_enabled,
            "continuous": True,
        }
        state.oracle = oracle

        # ── Start IPv8 peer ───────────────────────────────────────────────
        state.event(f"Starting peer on port {port}…", "info")
        builder = ConfigBuilder().clear_keys().clear_overlays()
        os.makedirs(Path(self.key_path).parent, exist_ok=True)
        builder.add_key("my peer", "medium", self.key_path)
        builder.set_port(port)

        from ipv8.configuration import BootstrapperDefinition, Bootstrapper
        from ipv8.configuration import DISPERSY_BOOTSTRAPPER
        bootstrap_defs = list(default_bootstrap_defs)
        if self.bootstrap_addresses:
            extra_init = dict(DISPERSY_BOOTSTRAPPER["init"])
            extra_init = {
                "ip_addresses": self.bootstrap_addresses,
                "dns_addresses": [],
            }
            bootstrap_defs.append(
                BootstrapperDefinition(Bootstrapper.DispersyBootstrapper, extra_init)
            )

        builder.add_overlay(
            "LTRMABCommunity", "my peer",
            [WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
            bootstrap_defs, {}, [("started",)],
        )

        ipv8 = IPv8(
            builder.finalize(),
            extra_communities={"LTRMABCommunity": LTRMABCommunity},
        )
        await ipv8.start()

        try:
            community: LTRMABCommunity = ipv8.get_overlay(LTRMABCommunity)
            state.community = community
            community.on_event = state.event

            state.event(f"Peer started (id={community.peer_id}). Discovering network…", "info")

            my_pid = str(os.getpid())
            known_entries = _register_self(my_pid, "127.0.0.1", port)
            walked: set[tuple[str, int]] = set()

            def _walk_new_peers(entries: dict) -> None:
                for _pid, entry in entries.items():
                    host, peer_port = entry[0], int(entry[1])
                    addr = (host, peer_port)
                    if addr in walked:
                        continue
                    walked.add(addr)
                    state.event(f"Walking to known local peer at {host}:{peer_port}", "info")
                    try:
                        community.walk_to(addr)
                    except Exception as exc:
                        state.event(f"walk_to({host}:{peer_port}) failed: {exc}", "info")

            _walk_new_peers(known_entries)

            # Wait for peer discovery, re-reading the registry each tick so
            # we notice peers that started after us, and heartbeating our own
            # entry so they don't treat us as stale.
            DISCOVERY_WAIT = 10  # seconds
            last_heartbeat = time.time()
            for elapsed_s in range(1, DISCOVERY_WAIT + 1):
                if self._stop_event.is_set():
                    return
                await asyncio.sleep(1)
                if time.time() - last_heartbeat >= _REGISTRY_HEARTBEAT_SECONDS:
                    _register_self(my_pid, "127.0.0.1", port)
                    last_heartbeat = time.time()
                _walk_new_peers(_register_self(my_pid, "127.0.0.1", port))
                n = len(community.get_peers())
                state.event(
                    f"Discovery {elapsed_s}/{DISCOVERY_WAIT}s — {n} network peer(s) found so far",
                    "info",
                )
                if n > 0 and elapsed_s >= 5:
                    break

            if self._stop_event.is_set():
                return

            n_final = len(community.get_peers())
            state.event(
                f"Discovery complete — {n_final} network peer(s) connected. Starting rounds.",
                "info",
            )

            self.started_ok.emit()

            # ── Continuous query / gossip loop ────────────────────────────
            # B2: no fixed round count. The peer runs indefinitely — queries
            # are processed continuously, and gossip + exclusion checks fire
            # on each `tick` (every `queries_per_round` queries). Each tick
            # produces one entry in `round_history` so the existing UI (which
            # plots per-round snapshots) keeps working unchanged.
            # Seeded query sampler. In the threaded runner we don't know our
            # own peer_id ahead of time (it's assigned when the community is
            # created), so we tag with pid to give each running instance a
            # distinct-yet-deterministic stream under a shared SEED.
            rng = _derive_rng(SEED, str(os.getpid()), "thread_queries")
            total_queries = len(query_boundaries)
            tick = 0
            queries_since_tick = 0
            QUERY_BATCH = 10               # queries per scheduling slice
            INTER_QUERY_SLEEP = 0.01       # yield to the event loop
            hotswap_done = False

            # Wall-clock cadence for gossip + TTL eviction. Decoupled from
            # query throughput: a slow peer doesn't gossip more often, a
            # fast one doesn't gossip less. One emission per interval to
            # exactly one random stranger.
            last_gossip_emit = time.time()

            state.phase = "querying"
            state.event(
                "Entering continuous operation — gossip every "
                f"{GOSSIP_INTERVAL_S:.0f}s to a random stranger.",
                "info",
            )

            while not self._stop_event.is_set():
                # --- Process a small batch of queries ---
                batch = min(QUERY_BATCH, self.queries_per_round - queries_since_tick)
                if batch <= 0:
                    batch = 1
                replace = batch > total_queries
                query_indices = rng.choice(
                    total_queries, size=batch, replace=replace
                )
                for qi in query_indices:
                    community.process_query(int(qi))
                queries_since_tick += batch
                await asyncio.sleep(INTER_QUERY_SLEEP)

                # --- Wall-clock gossip emission (single tuple to one stranger) ---
                if (
                    self.gossip_enabled
                    and time.time() - last_gossip_emit >= GOSSIP_INTERVAL_S
                ):
                    sent = await community.send_gossip()
                    if sent:
                        state.event(
                            "Gossiped one tuple to a random stranger", "gossip"
                        )
                    # Drop expired peer-observation entries so stale peers
                    # stop influencing the aggregate.
                    evicted = community.bandit.evict_all_stale()
                    if evicted:
                        state.event(
                            f"Evicted {evicted} stale peer-observation entries",
                            "info",
                        )
                    last_gossip_emit = time.time()

                # Not yet at a tick boundary — keep querying.
                if queries_since_tick < self.queries_per_round:
                    continue

                # --- Tick boundary: snapshot + survival check ---
                tick += 1
                queries_since_tick = 0
                state.current_round = tick

                # Optional one-shot hot-swap at a specific tick.
                if (
                    not hotswap_done
                    and self.hotswap_round > 0
                    and tick == self.hotswap_round
                    and hotswap_model_name
                ):
                    state.event(
                        f"HOT-SWAP: proposing {hotswap_model_name}", "round"
                    )
                    await community.propose_model(hotswap_model_name)
                    hotswap_done = True
                    await asyncio.sleep(0.2)

                # --- Survival / exclusion check ---
                # Each peer reaches its own verdict from the gossip-aggregated
                # evidence (own + non-stale peer observations). There is no
                # exclusion broadcast: a peer announcing "exclude k" would let
                # a single bad actor evict the best arm. Agreement comes from
                # peers seeing similar evidence, not explicit verdicts.
                state.phase = "survival"
                excluded_this_tick = community.check_exclusions(tick)
                for model_name in excluded_this_tick:
                    lcb, ucb = community.bandit.confidence_bounds(model_name)
                    reason = f"UCB={ucb:.3f} < best_LCB"
                    state.event(f"ARM EXCLUDED: {model_name} ({reason})", "exclusion")
                    await asyncio.sleep(0.02)

                # --- Record tick snapshot (schema unchanged: keyed on "round") ---
                stats = community.bandit.get_stats()
                arm_pulls = {n: s["pulls"] for n, s in stats.items()}
                arm_mean_reward = {
                    n: round(community._get_mean_reward(s), 4) for n, s in stats.items()
                }
                cumulative_reward = community.cumulative_scores.get(10, 0.0)
                best_oracle_score = max(oracle.values()) if oracle else 0.0
                oracle_cumulative = best_oracle_score * community.queries_processed

                prev_arms = (
                    set(state.round_history[-1]["arm_pulls"].keys())
                    if state.round_history else set()
                )
                tick_snapshot = {
                    "round": tick,
                    "arm_pulls": arm_pulls,
                    "arm_mean_reward": arm_mean_reward,
                    "cumulative_reward": round(cumulative_reward, 4),
                    "oracle_cumulative": round(oracle_cumulative, 4),
                    "new_arms": [n for n in arm_pulls if n not in prev_arms],
                }
                state.round_history.append(tick_snapshot)

                best = community.bandit.get_best_arm()
                state.event(
                    f"Tick {tick} · best={best} · "
                    f"active={len(community.active_models)} · "
                    f"excluded={len(community.excluded_models)}",
                    "round",
                )

                # Reset per-tick counters on the community so its internal
                # "round" bookkeeping tracks ticks rather than stale rounds.
                community.reset_round_stats()
                state.phase = "querying"

                # Heartbeat our registry entry so a peer that starts mid-run
                # can still discover us (and we don't get pruned as stale).
                if time.time() - last_heartbeat >= _REGISTRY_HEARTBEAT_SECONDS:
                    _walk_new_peers(_register_self(my_pid, "127.0.0.1", port))
                    last_heartbeat = time.time()

            state.event("Experiment stopped by user.", "round")
            self.finished_ok.emit()

        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            state.phase = "finished"
            state._emit_snapshot()
            try:
                if state.community is not None and state.community.seeder is not None:
                    state.community.seeder.shutdown()
            except Exception:
                pass
            try:
                await ipv8.stop()
            except Exception:
                pass
            try:
                reg = _read_peer_registry()
                reg.pop(str(os.getpid()), None)
                _write_peer_registry(reg)
            except Exception:
                pass

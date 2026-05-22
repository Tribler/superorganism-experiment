#!/usr/bin/env python3
"""HTTP collector for mycelium offline-sim events (TODO 8.7).

Accepts POST /event payloads from each container's EventLogger and appends
"""
import json
import os
import random
import subprocess
import time
import threading
import pathlib
import urllib.request
from datetime import datetime

from flask import Flask, request, jsonify

SIM_DIR = pathlib.Path(__file__).resolve().parent
FAUCET_SCRIPT = SIM_DIR / "btc" / "faucet.py"

BIND_HOST = "0.0.0.0"  # bind to lxdbr0 too so containers can POST events from the bridge
BIND_PORT = 8765
_RUN_TS = datetime.now().strftime("%d-%m-%Y-%H:%M")
EVENTS_FILE = SIM_DIR / "data" / f"{_RUN_TS}.jsonl"
# Matches what the bootstrapper writes to ~/.mycelium/log_secret and injects as
# MYCELIUM_LOG_SECRET on every node. It's just a logging endpoint, not real auth.
API_KEY = "123456789"
_REQUIRED_KEYS = ("timestamp", "node", "event", "data")
_lock = threading.Lock()

# Periodic economy faucet — see sim_config.toml [genesis] faucet_* knobs. The
# collector is the natural host for this: it already sees every state_snapshot
# (which carries the BTC address) and every server_expired (emitted by
# mock_sporestack when a container is reaped).
TIME_SCALE              = float(os.getenv("MYCELIUM_SIM_TIME_SCALE", "1"))
BTC_USD                 = float(os.getenv("MYCELIUM_SIM_BTC_USD", "0"))
MONTHLY_COST_CENTS      = float(os.getenv("MYCELIUM_SIM_MONTHLY_COST_CENTS", "0"))
FAUCET_MAX_MULTIPLIER   = float(os.getenv("MYCELIUM_SIM_FAUCET_MAX_MULTIPLIER", "1.2"))
FAUCET_MIN_FLOOR        = float(os.getenv("MYCELIUM_SIM_FAUCET_MIN_FLOOR", "0.5"))
FAUCET_DAYS_PER_MONTH   = float(os.getenv("MYCELIUM_SIM_FAUCET_DAYS_PER_MONTH", "30"))
FAUCET_PAUSE_THRESHOLD  = int(os.getenv("MYCELIUM_SIM_FAUCET_PAUSE_THRESHOLD", "50"))
FAUCET_RESUME_THRESHOLD = int(os.getenv("MYCELIUM_SIM_FAUCET_RESUME_THRESHOLD", "40"))
# Heartbeat-window eviction: server_expired only fires for reaper-driven expiry,
# so crashes/kills/failsafes leave ghosts in _live_nodes. Mirror the notebook's
# sliding-window definition by evicting entries that haven't snapshotted in
# LIVE_TIMEOUT_HEARTBEATS heartbeats.
HEARTBEAT_INTERVAL_S    = float(os.getenv("MYCELIUM_SIM_HEARTBEAT_INTERVAL", "10"))
LIVE_TIMEOUT_HEARTBEATS = float(os.getenv("MYCELIUM_SIM_LIVE_TIMEOUT_HEARTBEATS", "10"))
LIVE_NODE_TIMEOUT_S     = HEARTBEAT_INTERVAL_S * LIVE_TIMEOUT_HEARTBEATS
MOCK_SPORESTACK_URL     = os.getenv(
    "MYCELIUM_SIM_SPORESTACK_URL",
    f"http://127.0.0.1:{os.getenv('MYCELIUM_SIM_MOCK_PORT', '8766')}",
)
_live_nodes: dict[str, tuple[str, float]] = {}  # friendly_name -> (btc_address, last_seen_ts)
_live_lock = threading.Lock()


def _append(record: dict) -> None:
    with _lock:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")


def _update_live_nodes(event_name: str, node: str, data: dict) -> None:
    if event_name == "state_snapshot":
        now = time.time()
        addr = data.get("btc_address")
        with _live_lock:
            prev_addr = _live_nodes.get(node, ("", 0.0))[0]
            new_addr = addr if isinstance(addr, str) and addr else prev_addr
            _live_nodes[node] = (new_addr, now)
    elif event_name == "server_expired":
        name = data.get("friendly_name") or node
        with _live_lock:
            _live_nodes.pop(name, None)


def _force_reap(name: str) -> None:
    """Tell mock_sporestack to lxc stop + delete the container for `name`.

    Mock is idempotent (204 if already gone); on connection failure we just log
    and rely on the mock's own reaper to clean up at natural expiry.
    """
    if not name:
        return
    payload = json.dumps({"friendly_name": name}).encode()
    req = urllib.request.Request(
        f"{MOCK_SPORESTACK_URL}/sim/force_reap",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as e:
        print(f"[event_collector] force_reap {name} failed: {e}", flush=True)


def _live_nodes_eviction_loop() -> None:
    """Drop entries whose last state_snapshot is older than LIVE_NODE_TIMEOUT_S,
    and tell mock_sporestack to kill the underlying container."""
    period = max(1.0, LIVE_NODE_TIMEOUT_S / 2)
    while True:
        time.sleep(period)
        cutoff = time.time() - LIVE_NODE_TIMEOUT_S
        with _live_lock:
            stale = [n for n, (_addr, ts) in _live_nodes.items() if ts < cutoff]
            for n in stale:
                _live_nodes.pop(n, None)
        for n in stale:
            _force_reap(n)


def _faucet_drip_loop() -> None:
    """Once per sim-day, drip a node-count-aware total across live nodes.

    daily_max_btc    = active_nodes * monthly_cost_btc * MULTIPLIER / DAYS_PER_MONTH
    daily_actual_btc = daily_max_btc * uniform(FAUCET_MIN_FLOOR, 1.0)

    Hysteresis: pause entirely when active >= PAUSE_THRESHOLD; resume only when
    active <= RESUME_THRESHOLD. Paused ticks still log a `faucet_drip` event
    (with paused=true, total_btc=0) so analysis can see the gap.
    """
    if BTC_USD <= 0 or MONTHLY_COST_CENTS <= 0:
        return  # faucet disabled
    period_real_s = 86400.0 / TIME_SCALE
    sim_start_wall = time.time()
    monthly_cost_btc = (MONTHLY_COST_CENTS / 100.0) / BTC_USD
    print(f"[event_collector] faucet drip loop: every {period_real_s:.2f}s real "
          f"(1 sim-day); monthly_cost_btc={monthly_cost_btc:.8f}, "
          f"multiplier={FAUCET_MAX_MULTIPLIER}, floor={FAUCET_MIN_FLOOR}, "
          f"days_per_month={FAUCET_DAYS_PER_MONTH}, "
          f"pause>={FAUCET_PAUSE_THRESHOLD}, resume<={FAUCET_RESUME_THRESHOLD}",
          flush=True)
    paused = False
    while True:
        time.sleep(period_real_s)
        sim_days = (time.time() - sim_start_wall) * TIME_SCALE / 86400.0
        with _live_lock:
            targets = [(name, addr) for name, (addr, _ts) in _live_nodes.items()]
        active = len(targets)

        if not paused and active >= FAUCET_PAUSE_THRESHOLD:
            paused = True
            _append({
                "ts": time.time(),
                "src_ip": "127.0.0.1",
                "timestamp": datetime.now().astimezone().isoformat(),
                "node": "event_collector",
                "event": "faucet_paused",
                "data": {"sim_days": sim_days, "active_nodes": active,
                         "threshold": FAUCET_PAUSE_THRESHOLD},
            })
        elif paused and active <= FAUCET_RESUME_THRESHOLD:
            paused = False
            _append({
                "ts": time.time(),
                "src_ip": "127.0.0.1",
                "timestamp": datetime.now().astimezone().isoformat(),
                "node": "event_collector",
                "event": "faucet_resumed",
                "data": {"sim_days": sim_days, "active_nodes": active,
                         "threshold": FAUCET_RESUME_THRESHOLD},
            })

        if paused or active == 0:
            _append({
                "ts": time.time(),
                "src_ip": "127.0.0.1",
                "timestamp": datetime.now().astimezone().isoformat(),
                "node": "event_collector",
                "event": "faucet_drip",
                "data": {
                    "sim_days": sim_days,
                    "paused": paused,
                    "active_nodes": active,
                    "total_btc": 0,
                },
            })
            continue

        daily_max_btc = (
            active * monthly_cost_btc * FAUCET_MAX_MULTIPLIER / FAUCET_DAYS_PER_MONTH
        )
        daily_actual_btc = daily_max_btc * random.uniform(FAUCET_MIN_FLOOR, 1.0)
        weights = [random.expovariate(1.0) for _ in targets]
        s = sum(weights)
        shares = [w / s * daily_actual_btc for w in weights]
        per_node = {}
        for (name, addr), share in zip(targets, shares):
            per_node[name] = share
            if not addr:
                continue  # node alive but hasn't reported a BTC address yet
            try:
                subprocess.run(
                    [str(FAUCET_SCRIPT), "send", addr, f"{share:.8f}"],
                    check=False, timeout=30,
                )
            except Exception as e:
                print(f"[event_collector] faucet send to {name} ({addr}) failed: {e}",
                      flush=True)
        _append({
            "ts": time.time(),
            "src_ip": "127.0.0.1",
            "timestamp": datetime.now().astimezone().isoformat(),
            "node": "event_collector",
            "event": "faucet_drip",
            "data": {
                "sim_days": sim_days,
                "paused": False,
                "active_nodes": active,
                "daily_max_btc": daily_max_btc,
                "daily_actual_btc": daily_actual_btc,
                "total_btc": daily_actual_btc,
                "per_node_btc": per_node,
            },
        })


app = Flask(__name__)


@app.post("/event")
def event():
    if request.headers.get("X-Api-Key") != API_KEY:
        return ("unauthorized", 401)
    payload = request.get_json(silent=True)
    if payload is None or any(k not in payload for k in _REQUIRED_KEYS) \
            or not isinstance(payload["data"], dict):
        return ("bad request", 400)
    record = {"ts": time.time(), "src_ip": request.remote_addr, **payload}
    _append(record)
    _update_live_nodes(payload["event"], payload["node"], payload["data"])
    return ("", 204)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, events_file=str(EVENTS_FILE))


if __name__ == "__main__":
    threading.Thread(target=_faucet_drip_loop, daemon=True).start()
    threading.Thread(target=_live_nodes_eviction_loop, daemon=True).start()
    app.run(host=BIND_HOST, port=BIND_PORT, threaded=True)

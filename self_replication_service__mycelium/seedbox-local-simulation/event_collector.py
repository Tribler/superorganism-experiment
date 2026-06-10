#!/usr/bin/env python3
"""HTTP collector for mycelium offline-sim events (TODO 8.7).

Accepts POST /event payloads from each container's EventLogger and appends
"""
import base64
import json
import os
import random
import time
import threading
import pathlib
import urllib.request
from datetime import datetime
from typing import NamedTuple, Optional

from flask import Flask, request, jsonify

SIM_DIR = pathlib.Path(__file__).resolve().parent

# Same wallet as faucet.py/miner.py — drip uses one batched sendmany instead of N subprocess calls.
BTC_RPC_URL = "http://127.0.0.1:18443/wallet/mycelium-regtest"
_BTC_RPC_AUTH = base64.b64encode(b"mycelium:regtest").decode()


def _btc_rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "1.0", "id": "faucet",
                       "method": method, "params": params}).encode()
    req = urllib.request.Request(
        BTC_RPC_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {_BTC_RPC_AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if out.get("error"):
        raise RuntimeError(out["error"])
    return out["result"]

BIND_HOST = "0.0.0.0"  # bind to lxdbr0 too so containers can POST events from the bridge
BIND_PORT = 8765
_RUN_TS = datetime.now().strftime("%d-%m-%Y-%H:%M")
EVENTS_FILE = SIM_DIR / "data" / f"{_RUN_TS}.jsonl"
# Matches MYCELIUM_LOG_SECRET on every node — logging endpoint, not real auth.
API_KEY = "123456789"
_REQUIRED_KEYS = ("timestamp", "node", "event", "data")
_lock = threading.Lock()

# Faucet lives here: collector already sees state_snapshots (BTC addresses) and server_expired events.
TIME_SCALE              = float(os.getenv("MYCELIUM_SIM_TIME_SCALE", "1"))
BTC_USD                 = float(os.getenv("MYCELIUM_SIM_BTC_USD", "0"))
MONTHLY_COST_CENTS      = float(os.getenv("MYCELIUM_SIM_MONTHLY_COST_CENTS", "0"))
FAUCET_ENABLED          = os.getenv("MYCELIUM_SIM_FAUCET_ENABLED", "true").lower() == "true"
FAUCET_MAX_MULTIPLIER   = float(os.getenv("MYCELIUM_SIM_FAUCET_MAX_MULTIPLIER", "1.2"))
FAUCET_MIN_FLOOR        = float(os.getenv("MYCELIUM_SIM_FAUCET_MIN_FLOOR", "0.5"))
FAUCET_DAYS_PER_MONTH   = float(os.getenv("MYCELIUM_SIM_FAUCET_DAYS_PER_MONTH", "30"))
FAUCET_PAUSE_THRESHOLD  = int(os.getenv("MYCELIUM_SIM_FAUCET_PAUSE_THRESHOLD", "50"))
FAUCET_RESUME_THRESHOLD = int(os.getenv("MYCELIUM_SIM_FAUCET_RESUME_THRESHOLD", "40"))
# server_expired only fires for clean reaper expiry — crashes leave ghosts; evict on missed heartbeats.
HEARTBEAT_INTERVAL_S    = float(os.getenv("MYCELIUM_SIM_HEARTBEAT_INTERVAL", "10"))
LIVE_TIMEOUT_HEARTBEATS = float(os.getenv("MYCELIUM_SIM_LIVE_TIMEOUT_HEARTBEATS", "10"))
LIVE_NODE_TIMEOUT_S     = HEARTBEAT_INTERVAL_S * LIVE_TIMEOUT_HEARTBEATS
# Eviction is funding-gated: project runway forward by elapsed sim-time, reap only below floor.
REAP_RUNWAY_FLOOR_DAYS  = float(os.getenv("MYCELIUM_SIM_REAP_RUNWAY_FLOOR_DAYS", "0"))
MOCK_SPORESTACK_URL     = os.getenv(
    "MYCELIUM_SIM_SPORESTACK_URL",
    f"http://127.0.0.1:{os.getenv('MYCELIUM_SIM_MOCK_PORT', '8766')}",
)


class LiveNode(NamedTuple):
    """Last-known state of a live node, used to gate heartbeat-window eviction on
    projected runway rather than telemetry silence alone."""
    addr: str
    last_seen: float
    total_runway_days: Optional[float] = None
    days_remaining: Optional[float] = None
    btc_balance_sat: float = 0.0


_live_nodes: dict[str, LiveNode] = {}  # friendly_name -> LiveNode
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
            prev = _live_nodes.get(node)
            prev_addr = prev.addr if prev else ""
            new_addr = addr if isinstance(addr, str) and addr else prev_addr
            # Absent fields carry forward so a partial heartbeat never erases known-good runway inputs.
            total_runway = data.get("total_runway_days")
            if total_runway is None:
                total_runway = prev.total_runway_days if prev else None
            days_remaining = data.get("days_remaining")
            if days_remaining is None:
                days_remaining = prev.days_remaining if prev else None
            btc_balance_sat = data.get("btc_balance_sat")
            if btc_balance_sat is None:
                btc_balance_sat = prev.btc_balance_sat if prev else 0.0
            _live_nodes[node] = LiveNode(
                addr=new_addr,
                last_seen=now,
                total_runway_days=total_runway,
                days_remaining=days_remaining,
                btc_balance_sat=btc_balance_sat,
            )
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


def _projected_runway_days(node: LiveNode, now: float) -> Optional[float]:
    """Last-known total runway minus sim-days elapsed since the last heartbeat.
    Returns None when runway can't be determined (still booting)."""
    elapsed_sim_days = (now - node.last_seen) * TIME_SCALE / 86400.0
    if node.total_runway_days is not None:
        return node.total_runway_days - elapsed_sim_days
    # Fallback: reconstruct from days_remaining + BTC reserve (mirrors node_monitor).
    if node.days_remaining is None:
        return None
    runway = float(node.days_remaining)
    if MONTHLY_COST_CENTS > 0 and BTC_USD > 0:
        cost_per_day_cents = MONTHLY_COST_CENTS / 30.0
        btc_cents = (node.btc_balance_sat / 1e8) * BTC_USD * 100.0
        runway += btc_cents / cost_per_day_cents
    return runway - elapsed_sim_days


def _live_nodes_eviction_loop() -> None:
    """A missed-heartbeat window only triggers a funding evaluation; the reap is
    funding-gated. Silent-but-funded nodes stay in _live_nodes and are re-evaluated
    each cycle, reaped only once their projected runway crosses the floor. This
    bounds how long a genuinely-crashed node lingers (≈ its last-known runway in
    sim-time) without ever destroying a node the sim still believes is funded."""
    period = max(1.0, LIVE_NODE_TIMEOUT_S / 2)
    while True:
        time.sleep(period)
        now = time.time()
        cutoff = now - LIVE_NODE_TIMEOUT_S
        to_reap: list[tuple[str, float]] = []
        spared: list[tuple[str, float]] = []
        with _live_lock:
            candidates = [(n, e) for n, e in _live_nodes.items() if e.last_seen < cutoff]
            for n, e in candidates:
                proj = _projected_runway_days(e, now)
                if proj is None:
                    continue  # unknown runway → wait (don't kill a booting node)
                if proj <= REAP_RUNWAY_FLOOR_DAYS:
                    to_reap.append((n, proj))
                    _live_nodes.pop(n, None)
                else:
                    spared.append((n, proj))
        for n, proj in spared:
            print(f"[event_collector] silent {n} — still funded, projected "
                  f"{proj:.2f} sim-days runway; not reaping", flush=True)
        for n, proj in to_reap:
            print(f"[event_collector] reaped {n} — projected runway {proj:.2f} "
                  f"sim-days <= floor {REAP_RUNWAY_FLOOR_DAYS}", flush=True)
            _force_reap(n)


def _faucet_drip_loop() -> None:
    """Once per sim-day, drip a node-count-aware total across live nodes.

    daily_max_btc    = active_nodes * monthly_cost_btc * MULTIPLIER / DAYS_PER_MONTH
    daily_actual_btc = daily_max_btc * uniform(FAUCET_MIN_FLOOR, 1.0)

    Hysteresis: pause entirely when active >= PAUSE_THRESHOLD; resume only when
    active <= RESUME_THRESHOLD. Paused ticks still log a `faucet_drip` event
    (with paused=true, total_btc=0) so analysis can see the gap.
    """
    if not FAUCET_ENABLED:
        print("[event_collector] faucet drip disabled (faucet_enabled=false)", flush=True)
        return
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
            targets = [(name, e.addr) for name, e in _live_nodes.items()]
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
        outputs = {}
        for (name, addr), share in zip(targets, shares):
            per_node[name] = share
            if not addr:
                continue  # node alive but hasn't reported a BTC address yet
            # sendmany keys must be unique — sum if two nodes share an address. 8dp = satoshi precision.
            outputs[addr] = round(outputs.get(addr, 0.0) + share, 8)
        if outputs:
            try:
                _btc_rpc("sendmany", ["", outputs])
            except Exception as e:
                print(f"[event_collector] faucet sendmany failed: {e}", flush=True)
        # miner.py drains the mempool and confirms within ~1s — no generatetoaddress here.
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

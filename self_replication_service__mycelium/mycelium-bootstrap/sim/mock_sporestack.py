#!/usr/bin/env python3
"""Mock SporeStack API for mycelium sim

Mycelium `/sporestack_client.py` calls:
  GET  /token                        text/plain token
  GET  /token/{t}/info               {balance_cents, burn_rate_cents}
  GET  /token/{t}/balance            {cents}
  POST /token/{t}/add                {invoice: {payment_uri, created, expires, …}}
  GET  /token/{t}/servers            {servers: [...]}
  GET  /token/{t}/servers/{m}        full server dict (ipv4, expiration, …)
  POST /token/{t}/servers            {machine_id}
  GET  /server/quote                 {cents}

Sim-only endpoints:
  POST /sim/start/{m}                push env+secrets and start the entrypoint
  GET  /sim/health/{m}               {running}

State is in-memory; a daemon thread polls regtest invoices every 3s and credits
paid tokens.

A `threading.RLock` guards all dict mutations.

NON-OBVIOUS BEHAVIOUR:
MYCELIUM_SIM_MODE, MYCELIUM_SPORESTACK_BASE_URL,
MYCELIUM_BITCOIN_NETWORK, MYCELICELIUM_PUBLIC_IUM_IPV8_BOOTSTRAP
are injected on every /sim/start - instead of propagated node-to-node.

Time-scaling - MYCELIUM_SIM_TIME_SCALE (default 1000):
  - Server expiration = now + days*86400/TIME_SCALE (so a 30-day
    server lives 40 minutes at TIME_SCALE=1000).
  - /servers/{m} returns `expiration` projected forward by TIME_SCALE so
    node_monitor's unmodified `(expiration - now)/86400` reads sim-days.
  - balance_cents decays at the production cents/day rate against sim-elapsed time.
"""
import base64
import json
import math
import os
import pathlib
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Tuple

from flask import Flask, Response, jsonify, request


# ───── Config ──────────────────────────────────────────────────────────

BIND_HOST = os.getenv("MYCELIUM_SIM_MOCK_HOST", "0.0.0.0")
BIND_PORT = int(os.getenv("MYCELIUM_SIM_MOCK_PORT", "8766"))
TIME_SCALE = float(os.getenv("MYCELIUM_SIM_TIME_SCALE", "1000"))
BTC_USD = float(os.getenv("MYCELIUM_SIM_BTC_USD", "50000"))
MONTHLY_COST_CENTS = int(os.getenv("MYCELIUM_SIM_MONTHLY_COST_CENTS", "3000"))
INVOICE_LIFETIME_S = int(os.getenv("MYCELIUM_SIM_INVOICE_LIFETIME_S", "600"))
INVOICE_POLL_INTERVAL_S = float(os.getenv("MYCELIUM_SIM_INVOICE_POLL_S", "3"))
LXC_PROVISION_TIMEOUT_S = float(os.getenv("MYCELIUM_SIM_LXC_PROVISION_TIMEOUT_S", "30"))

LXC_BASE_IMAGE = os.getenv("MYCELIUM_SIM_LXC_BASE_IMAGE", "mycelium-base")
LXC_BRIDGE_NAME = os.getenv("MYCELIUM_SIM_LXC_BRIDGE", "lxdbr0")
ELECTRS_PORT = int(os.getenv("MYCELIUM_SIM_ELECTRS_PORT", "60401"))
EVENT_COLLECTOR_PORT = int(os.getenv("MYCELIUM_SIM_EVENT_COLLECTOR_PORT", "8765"))
IPV8_BOOTSTRAP_INSTANCE = os.getenv("MYCELIUM_SIM_BOOTSTRAP_INSTANCE", "ipv8-bootstrap")
IPV8_BOOTSTRAP_PORT = int(os.getenv("MYCELIUM_SIM_BOOTSTRAP_PORT", "7759"))

BTC_DATADIR = pathlib.Path.home() / ".mycelium-sim" / "regtest"
BCLI = [
    "bitcoin-cli", "-regtest", f"-datadir={BTC_DATADIR}",
    "-rpcuser=mycelium", "-rpcpassword=regtest",
    "-rpcconnect=127.0.0.1", "-rpcport=18443",
    "-rpcwallet=mycelium-regtest",
]


# ───── State ───────────────────────────────────────────────────────────

@dataclass
class TokenState:
    token: str
    cents_paid_in: int = 0
    created_at_wall: float = field(default_factory=time.time)
    server_ids: list = field(default_factory=list)
    invoice_ids: list = field(default_factory=list)


@dataclass
class Invoice:
    invoice_id: str
    token: str
    dollars_owed: int
    sat_owed: int
    pay_address: str
    created: int
    expires: int
    paid_txid: Optional[str] = None
    credited_at: Optional[float] = None


@dataclass
class ServerState:
    machine_id: str
    token: str
    ssh_key: str
    flavor: str
    operating_system: str
    provider: str
    region: str
    billing_cycle: str
    days: int
    hostname: str
    monthly_cost_cents: int
    created_at_wall: float
    expiration_wall_ts: float
    ipv4: str = ""
    ipv6: str = ""
    ssh_port: int = 22


_lock = threading.RLock()
_tokens: dict = {}      # token_str -> TokenState
_invoices: dict = {}    # invoice_id -> Invoice
_servers: dict = {}     # machine_id -> ServerState
_bridge_ip_cache: Optional[str] = None


# ───── Subprocess + LXC + BTC helpers ──────────────────────────────────

def _run_cli(cmd, *, timeout: float = 30.0) -> str:
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout,
    ).stdout.strip()


def _get_bridge_ip() -> str:
    """Detect the LXC bridge IP. Cached after first success."""
    global _bridge_ip_cache
    if _bridge_ip_cache:
        return _bridge_ip_cache
    override = os.getenv("MYCELIUM_SIM_BRIDGE_IP", "").strip()
    if override:
        _bridge_ip_cache = override
        return override
    try:
        cidr = _run_cli(["lxc", "network", "get", LXC_BRIDGE_NAME, "ipv4.address"], timeout=5)
        if cidr:
            _bridge_ip_cache = cidr.split("/", 1)[0]
            return _bridge_ip_cache
    except Exception:
        pass
    try:
        out = _run_cli(["ip", "-4", "-j", "addr", "show", LXC_BRIDGE_NAME], timeout=5)
        for iface in json.loads(out):
            for addr in iface.get("addr_info", []):
                if addr.get("family") == "inet":
                    ip = addr.get("local", "")
                    if ip:
                        _bridge_ip_cache = ip
                        return ip
    except Exception:
        pass
    raise RuntimeError(
        f"Cannot detect LXC bridge IP for '{LXC_BRIDGE_NAME}' "
        "(set MYCELIUM_SIM_BRIDGE_IP to override)"
    )


def _get_container_ipv4(machine_id: str) -> Tuple[str, str]:
    """Return (ipv4, ipv6) for a container by parsing `lxc list <m> --format json`."""
    out = _run_cli(["lxc", "list", machine_id, "--format", "json"], timeout=5)
    for inst in json.loads(out):
        if inst.get("name") != machine_id:
            continue
        net = (inst.get("state") or {}).get("network") or {}
        eth0 = net.get("eth0") or {}
        ipv4 = ""
        ipv6 = ""
        for addr in eth0.get("addresses", []):
            fam = addr.get("family")
            a = addr.get("address", "")
            if fam == "inet" and not ipv4:
                ipv4 = a
            elif fam == "inet6" and not ipv6 and not a.startswith("fe80"):
                ipv6 = a
        return ipv4, ipv6
    return "", ""


def _get_bootstrap_ip() -> Optional[str]:
    """IPv4 of the IPv8 bootstrap container, or None if it's not running."""
    try:
        ipv4, _ = _get_container_ipv4(IPV8_BOOTSTRAP_INSTANCE)
        return ipv4 or None
    except Exception:
        return None


def _lxc_init_and_start(machine_id: str) -> Tuple[str, str]:
    """`lxc init mycelium-base <id>` + `lxc start <id>`, then poll for IPv4."""
    _run_cli(["lxc", "init", LXC_BASE_IMAGE, machine_id], timeout=60)
    _run_cli(["lxc", "start", machine_id], timeout=30)

    deadline = time.time() + LXC_PROVISION_TIMEOUT_S
    while time.time() < deadline:
        try:
            ipv4, ipv6 = _get_container_ipv4(machine_id)
            if ipv4:
                return ipv4, ipv6
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"Container {machine_id} never got an IPv4 within {LXC_PROVISION_TIMEOUT_S}s"
    )


def _lxc_push_env_and_kick_entrypoint(machine_id: str, env_body: str) -> None:
    """Push /root/sim_env (mode 600) and detach the entrypoint via `lxc exec`."""
    fd, tmp_path = tempfile.mkstemp(prefix="sim_env_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(env_body)
        _run_cli(
            ["lxc", "file", "push", "--mode=600", tmp_path, f"{machine_id}/root/sim_env"],
            timeout=30,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    # Inner `&` detaches in-container; the outer `lxc exec` returns immediately.
    _run_cli(
        [
            "lxc", "exec", machine_id, "--",
            "sh", "-c",
            "mkdir -p /root/logs && nohup /usr/local/bin/mycelium-entrypoint "
            ">/root/logs/orchestrator.log 2>&1 </dev/null &",
        ],
        timeout=15,
    )


def _lxc_pgrep_main(machine_id: str) -> bool:
    """Mirrors SSHDeployer.check_health pgrep semantics: any failure returns False."""
    try:
        subprocess.run(
            ["lxc", "exec", machine_id, "--", "pgrep", "-f", "python.*main.py"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False


def _btc_new_address() -> str:
    return _run_cli(BCLI + ["getnewaddress"], timeout=10)


def _btc_received_by_address(addr: str) -> float:
    return float(_run_cli(BCLI + ["getreceivedbyaddress", addr, "0"], timeout=10))


def _btc_force_confirm() -> None:
    coinbase = _run_cli(BCLI + ["getnewaddress"], timeout=10)
    _run_cli(BCLI + ["generatetoaddress", "1", coinbase], timeout=10)


def _btc_txid_for_address(addr: str) -> str:
    try:
        out = _run_cli(
            BCLI + ["listreceivedbyaddress", "0", "true", "false", addr],
            timeout=10,
        )
        entries = json.loads(out)
        if entries and entries[0].get("txids"):
            return entries[0]["txids"][0]
    except Exception:
        pass
    return ""


# ───── Math helpers ────────────────────────────────────────────────────

def _btc_decimal(sat: int) -> str:
    """Render a satoshi amount as a clean BTC decimal string for BIP21."""
    return f"{sat / 1e8:.8f}".rstrip("0").rstrip(".") or "0"


def _sat_owed_for_dollars(dollars: int) -> int:
    return math.ceil(dollars * 100_000_000 / BTC_USD)


def _server_apparent_expiration(s: ServerState, now: float) -> int:
    """Project remaining wall-seconds * TIME_SCALE forward of `now`.

    node_monitor.refresh computes (expiration - time.time()) / 86400 as
    days_remaining; we want that to read sim-days, which means returning
    `now + (expiration_wall_ts - now) * TIME_SCALE`.
    """
    remaining_wall = max(0.0, s.expiration_wall_ts - now)
    return round(now + remaining_wall * TIME_SCALE)


def _cents_burned_for_server(s: ServerState, now: float) -> int:
    """Cents this server has consumed at the production rate against sim-elapsed time.

    Capped at expiration_wall_ts so a long-dead server doesn't keep burning the
    token's pool past its purchased lifetime.
    """
    elapsed_wall = max(0.0, min(now, s.expiration_wall_ts) - s.created_at_wall)
    elapsed_sim = elapsed_wall * TIME_SCALE
    return int(s.monthly_cost_cents * elapsed_sim / (30 * 86400))


def _token_balance_cents(t: TokenState, now: float) -> int:
    burned = sum(
        _cents_burned_for_server(_servers[sid], now)
        for sid in t.server_ids
        if sid in _servers
    )
    return max(0, t.cents_paid_in - burned)


def _server_to_dict(s: ServerState) -> dict:
    now = time.time()
    return {
        "machine_id": s.machine_id,
        "ipv4": s.ipv4,
        "ipv6": s.ipv6,
        "ssh_port": s.ssh_port,
        "expiration": _server_apparent_expiration(s, now),
        "provider": s.provider,
        "region": s.region,
        "flavor": s.flavor,
        "operating_system": s.operating_system,
        "hostname": s.hostname,
        "created_at": int(s.created_at_wall),
        "created": int(s.created_at_wall),
    }


def _build_sim_env_lines(env: dict, secrets_in: dict, container_ipv4: str) -> str:
    """Render the /root/sim_env body matching sim/image/entrypoint.sh's parser.

    Sim-side enrichment (the documented non-obvious behaviour) lives here.
    """
    bridge_ip = _get_bridge_ip()
    bootstrap_ip = _get_bootstrap_ip()

    enriched = dict(env)
    enriched["MYCELIUM_SIM_MODE"] = "1"
    enriched["MYCELIUM_SPORESTACK_BASE_URL"] = f"http://{bridge_ip}:{BIND_PORT}"
    enriched["MYCELIUM_BITCOIN_NETWORK"] = "regtest"
    enriched["MYCELIUM_PUBLIC_IP"] = container_ipv4 or enriched.get("MYCELIUM_PUBLIC_IP", "")
    if bootstrap_ip:
        enriched["MYCELIUM_IPV8_BOOTSTRAP"] = f"{bootstrap_ip}:{IPV8_BOOTSTRAP_PORT}"
    enriched.setdefault("MYCELIUM_LOG_ENDPOINT", f"http://{bridge_ip}:{EVENT_COLLECTOR_PORT}")

    providers = {
        "electrum_regtest": {
            "provider": "electrumx",
            "network": "regtest",
            "client_class": "ElectrumxClient",
            "provider_coin": "",
            "url": f"tcp://{bridge_ip}:{ELECTRS_PORT}",
            "api_key": "",
            "priority": 11,
            "denominator": 100_000_000,
            "network_overrides": None,
        }
    }
    enriched_secrets = dict(secrets_in)
    enriched_secrets["/root/.bitcoinlib/providers.json"] = json.dumps(providers, indent=2)

    lines = [f"{k}={v}" for k, v in enriched.items()]
    for path, content in enriched_secrets.items():
        b64 = base64.b64encode(content.encode()).decode()
        lines.append(f"__SECRET_B64__{path}={b64}")
    return "\n".join(lines) + "\n"


# ───── BTC invoice processing ──────────────────────────────────────────

def _credit_invoice(inv: Invoice, txid: str) -> None:
    """Caller holds _lock. Bump cents_paid_in and extend the primary server (if any)."""
    inv.paid_txid = txid
    inv.credited_at = time.time()
    tok = _tokens.get(inv.token)
    if not tok:
        return
    tok.cents_paid_in += inv.dollars_owed * 100
    if not tok.server_ids:
        return
    primary = _servers.get(tok.server_ids[0])
    if not primary:
        return
    extra_wall_seconds = (
        (inv.dollars_owed * 100 / MONTHLY_COST_CENTS) * 30 * 86400 / TIME_SCALE
    )
    base_ts = max(primary.expiration_wall_ts, time.time())
    primary.expiration_wall_ts = base_ts + extra_wall_seconds


def _invoice_poller_loop() -> None:
    """Daemon: every INVOICE_POLL_INTERVAL_S, scan unpaid invoices, credit on receipt."""
    while True:
        try:
            with _lock:
                pending = [inv for inv in _invoices.values() if inv.paid_txid is None]
            for inv in pending:
                try:
                    received_btc = _btc_received_by_address(inv.pay_address)
                except Exception:
                    continue
                received_sat = int(round(received_btc * 1e8))
                if received_sat < inv.sat_owed:
                    continue
                txid = _btc_txid_for_address(inv.pay_address) or "regtest-confirmed"
                try:
                    _btc_force_confirm()
                except Exception:
                    pass
                with _lock:
                    if inv.paid_txid is None:
                        _credit_invoice(inv, txid)
                        print(
                            f"[mock_sporestack] credited token={inv.token[:8]}.. "
                            f"+${inv.dollars_owed} (txid={txid[:12]}..)",
                            flush=True,
                        )
        except Exception as e:
            print(f"[mock_sporestack] invoice poller error: {e}", flush=True)
        time.sleep(INVOICE_POLL_INTERVAL_S)


# ───── Flask routes ────────────────────────────────────────────────────

app = Flask(__name__)


def _err_503(msg: str):
    return jsonify({"error": msg}), 503


@app.get("/healthz")
def healthz():
    with _lock:
        return jsonify(
            ok=True,
            tokens=len(_tokens),
            servers=len(_servers),
            invoices=len(_invoices),
            time_scale=TIME_SCALE,
        )


@app.get("/token")
def get_token():
    """Mint a synthetic token. text/plain per the production sporestack contract."""
    token = secrets.token_hex(16)
    with _lock:
        _tokens[token] = TokenState(token=token)
    return Response(token, mimetype="text/plain")


@app.get("/token/<token>/info")
def token_info(token: str):
    now = time.time()
    with _lock:
        tok = _tokens.get(token)
        if not tok:
            return jsonify({"error": "no such token"}), 404
        balance = _token_balance_cents(tok, now)
    return jsonify({
        "balance_cents": balance,
        "burn_rate_cents": int(MONTHLY_COST_CENTS / 30),
    })


@app.get("/token/<token>/balance")
def token_balance(token: str):
    now = time.time()
    with _lock:
        tok = _tokens.get(token)
        if not tok:
            return jsonify({"error": "no such token"}), 404
        cents = _token_balance_cents(tok, now)
    return jsonify({"cents": cents})


@app.post("/token/<token>/add")
def token_add(token: str):
    body = request.get_json(silent=True) or {}
    try:
        dollars = int(body.get("dollars", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "dollars must be int"}), 400
    if dollars < 1:
        return jsonify({"error": "dollars must be >= 1"}), 400

    with _lock:
        if token not in _tokens:
            return jsonify({"error": "no such token"}), 404

    try:
        pay_address = _btc_new_address()
    except Exception as e:
        return _err_503(f"bitcoin-cli getnewaddress failed: {e}")

    sat_owed = _sat_owed_for_dollars(dollars)
    btc_str = _btc_decimal(sat_owed)
    payment_uri = f"bitcoin:{pay_address}?amount={btc_str}"

    now = int(time.time())
    invoice_id = uuid.uuid4().hex
    invoice = Invoice(
        invoice_id=invoice_id,
        token=token,
        dollars_owed=dollars,
        sat_owed=sat_owed,
        pay_address=pay_address,
        created=now,
        expires=now + INVOICE_LIFETIME_S,
    )
    with _lock:
        _invoices[invoice_id] = invoice
        _tokens[token].invoice_ids.append(invoice_id)

    return jsonify({
        "invoice": {
            "payment_uri": payment_uri,
            "created": invoice.created,
            "expires": invoice.expires,
            "address": pay_address,
            "amount_btc": btc_str,
            "amount_sat": sat_owed,
        }
    })


@app.get("/token/<token>/servers")
def token_servers(token: str):
    with _lock:
        tok = _tokens.get(token)
        if not tok:
            return jsonify({"error": "no such token"}), 404
        servers = [
            _server_to_dict(_servers[sid])
            for sid in tok.server_ids
            if sid in _servers
        ]
    return jsonify({"servers": servers})


@app.get("/token/<token>/servers/<machine_id>")
def token_server_one(token: str, machine_id: str):
    with _lock:
        if token not in _tokens:
            return jsonify({"error": "no such token"}), 404
        s = _servers.get(machine_id)
        if not s or s.token != token:
            return jsonify({"error": "no such server"}), 404
        return jsonify(_server_to_dict(s))


@app.post("/token/<token>/servers")
def token_server_create(token: str):
    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days < 1:
        return jsonify({"error": "days must be >= 1"}), 400

    with _lock:
        if token not in _tokens:
            return jsonify({"error": "no such token"}), 404

    machine_id = "m-" + uuid.uuid4().hex[:12]
    try:
        ipv4, ipv6 = _lxc_init_and_start(machine_id)
    except Exception as e:
        return _err_503(f"lxc provision failed: {e}")

    now = time.time()
    server = ServerState(
        machine_id=machine_id,
        token=token,
        ssh_key=body.get("ssh_key", ""),
        flavor=body.get("flavor", ""),
        operating_system=body.get("operating_system", ""),
        provider=body.get("provider", ""),
        region=body.get("region", ""),
        billing_cycle=body.get("billing_cycle", "monthly"),
        days=days,
        hostname=body.get("hostname", ""),
        monthly_cost_cents=MONTHLY_COST_CENTS,
        created_at_wall=now,
        expiration_wall_ts=now + days * 86400 / TIME_SCALE,
        ipv4=ipv4,
        ipv6=ipv6,
        ssh_port=22,
    )
    with _lock:
        _servers[machine_id] = server
        _tokens[token].server_ids.append(machine_id)

    return jsonify({"machine_id": machine_id})


@app.get("/server/quote")
def server_quote():
    try:
        days = int(request.args.get("days", "30"))
    except (TypeError, ValueError):
        days = 30
    return jsonify({"cents": int(MONTHLY_COST_CENTS * days / 30)})


# ───── Sim-only endpoints ──────────────────────────────────────────────

@app.post("/sim/start/<machine_id>")
def sim_start(machine_id: str):
    body = request.get_json(silent=True) or {}
    env = body.get("env") or {}
    secrets_in = body.get("secrets") or {}
    if not isinstance(env, dict) or not isinstance(secrets_in, dict):
        return jsonify({"error": "env and secrets must be objects"}), 400

    with _lock:
        s = _servers.get(machine_id)
        if not s:
            return jsonify({"error": "no such server"}), 404
        ipv4 = s.ipv4

    try:
        env_body = _build_sim_env_lines(env, secrets_in, ipv4)
        _lxc_push_env_and_kick_entrypoint(machine_id, env_body)
    except Exception as e:
        return _err_503(f"sim/start failed: {e}")
    return ("", 200)


@app.get("/sim/health/<machine_id>")
def sim_health(machine_id: str):
    with _lock:
        if machine_id not in _servers:
            return jsonify({"error": "no such server"}), 404
    return jsonify({"running": _lxc_pgrep_main(machine_id)})


# ───── Entrypoint ──────────────────────────────────────────────────────

def main() -> None:
    poller = threading.Thread(
        target=_invoice_poller_loop, name="invoice-poller", daemon=True,
    )
    poller.start()
    print(
        f"[mock_sporestack] listening on {BIND_HOST}:{BIND_PORT} "
        f"(TIME_SCALE={TIME_SCALE}, monthly_cost={MONTHLY_COST_CENTS}c)",
        flush=True,
    )
    app.run(host=BIND_HOST, port=BIND_PORT, threaded=True)


if __name__ == "__main__":
    main()

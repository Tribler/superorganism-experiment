#!/usr/bin/env python3
"""Top-level entry point for the mycelium offline sim (TODO 8.10).

Brings up the BTC regtest stack, event collector, mock SporeStack, IPv8
bootstrap container, and a single genesis mycelium node — then tails the
genesis orchestrator log. Companion teardown: stop_simulation.sh.

All tunable parameters live in sim_config.toml next to this file.
CLI flags override config values when provided.
"""
import argparse
import json
import math
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

SIM_DIR = pathlib.Path(__file__).resolve().parent
BOOTSTRAP_DIR = SIM_DIR.parent
SIM_HOME = pathlib.Path.home() / ".mycelium-sim"
LOG_DIR = SIM_HOME / "logs"

MYCELIUM_BASE_IMAGE = "mycelium-base"
IPV8_BOOTSTRAP_IMAGE = "ipv8-bootstrap-base"
IPV8_BOOTSTRAP_NAME = "ipv8-bootstrap"
GENESIS_NAME = "genesis"
BCLI_DATADIR = SIM_HOME / "regtest"
BCLI = [
    "bitcoin-cli", "-regtest", f"-datadir={BCLI_DATADIR}",
    "-rpcuser=mycelium", "-rpcpassword=regtest",
    "-rpcconnect=127.0.0.1", "-rpcport=18443",
    "-rpcwallet=mycelium-regtest",
]

os.environ.setdefault("MYCELIUM_SIM_MODE", "1")
sys.path.insert(0, str(BOOTSTRAP_DIR))
from lib.wallet import BitcoinWallet  # noqa: E402
from lib.deployer import generate_ssh_keypair  # noqa: E402


def load_config() -> dict:
    cfg_path = SIM_DIR / "sim_config.toml"
    with open(cfg_path, "rb") as f:
        return tomllib.load(f)


def _log(msg: str) -> None:
    print(f"[run_sim] {msg}", flush=True)


def _http_get_json(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _http_get_text(url: str, timeout: float = 15) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode().strip()


def _http_post_json(url: str, payload: dict, timeout: float = 30) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
    return json.loads(text) if text else {}


def _wait_for_healthz(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception as e:
            last_err = str(e)
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last_err}")


def preflight(cfg: dict) -> None:
    for binary in ("lxc", "bitcoind", "electrs", "bitcoin-cli"):
        if not shutil.which(binary):
            sys.exit(f"[run_sim] missing required binary: {binary}")
    bridge = cfg["network"]["lxc_bridge"]
    try:
        cidr = subprocess.check_output(
            ["lxc", "network", "get", bridge, "ipv4.address"],
            text=True, timeout=5,
        ).strip()
    except Exception as e:
        sys.exit(
            f"[run_sim] cannot read lxd bridge '{bridge}': {e}\n"
            "         Run `lxd init` and ensure the default bridge exists."
        )
    if not cidr:
        sys.exit(
            f"[run_sim] lxd bridge '{bridge}' has no ipv4.address — run `lxd init`"
        )


def start_btc_stack(cfg: dict) -> None:
    _log("starting BTC regtest stack...")
    os.environ["BTC_BLOCK_INTERVAL"] = str(cfg["btc"]["block_interval_s"])
    subprocess.run([str(SIM_DIR / "btc" / "start.sh")], check=True)


def _spawn_background(name: str, script_path: pathlib.Path,
                      extra_env: dict | None = None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SIM_HOME.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pkill", "-f", str(script_path)], check=False)
    time.sleep(0.5)
    log_path = LOG_DIR / f"{name}.log"
    pid_path = SIM_HOME / f"{name}.pid"
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    log_fp = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=log_fp, stderr=subprocess.STDOUT, env=env,
        start_new_session=True,
    )
    pid_path.write_text(str(proc.pid))


def start_event_collector(cfg: dict) -> None:
    _log("starting event collector...")
    event_collector_url = f"http://127.0.0.1:{cfg['network']['event_collector_port']}"
    _spawn_background("event_collector", SIM_DIR / "event_collector.py")
    _wait_for_healthz(f"{event_collector_url}/healthz")
    _log("event collector healthy")


def start_mock_sporestack(cfg: dict) -> None:
    ss = cfg["sporestack"]
    net = cfg["network"]
    ivl = cfg["intervals"]
    _log(f"starting mock SporeStack (time_scale={ss['time_scale']})...")
    extra_env = {
        "MYCELIUM_SIM_TIME_SCALE":          str(ss["time_scale"]),
        "MYCELIUM_SIM_BTC_USD":             str(ss["btc_usd"]),
        "MYCELIUM_SIM_MONTHLY_COST_CENTS":  str(ss["monthly_cost_cents"]),
        "MYCELIUM_SIM_INVOICE_LIFETIME_S":  str(ss["invoice_lifetime_s"]),
        "MYCELIUM_SIM_ELECTRS_PORT":        str(net["electrs_port"]),
        "MYCELIUM_SIM_EVENT_COLLECTOR_PORT": str(net["event_collector_port"]),
        "MYCELIUM_SIM_MOCK_PORT":           str(net["mock_sporestack_port"]),
        "MYCELIUM_SIM_BOOTSTRAP_PORT":      str(net["ipv8_bootstrap_port"]),
        "MYCELIUM_SIM_LXC_BRIDGE":          net["lxc_bridge"],
        # Interval defaults applied to every spawned node
        "MYCELIUM_SIM_DECISION_INTERVAL":      str(ivl["decision_interval"]),
        "MYCELIUM_SIM_HEARTBEAT_INTERVAL":     str(ivl["heartbeat_interval"]),
        "MYCELIUM_SIM_PEER_REGISTRY_TTL":      str(ivl["peer_registry_ttl"]),
        "MYCELIUM_SIM_WHOAMI_BROADCAST":       str(ivl["whoami_broadcast_interval"]),
        "MYCELIUM_SIM_WHOAMI_GOSSIP_COOLDOWN": str(ivl["whoami_gossip_cooldown"]),
        "MYCELIUM_SIM_UPDATE_CHECK_INTERVAL":  str(ivl["update_check_interval"]),
    }
    mock_sporestack_url = f"http://127.0.0.1:{net['mock_sporestack_port']}"
    _spawn_background("mock_sporestack", SIM_DIR / "mock_sporestack.py", extra_env=extra_env)
    _wait_for_healthz(f"{mock_sporestack_url}/healthz", timeout=60)
    _log("mock SporeStack healthy")


def _lxc_image_exists(alias: str) -> bool:
    try:
        out = subprocess.check_output(
            ["lxc", "image", "list", alias, "--format", "json"],
            text=True, timeout=15,
        )
    except subprocess.CalledProcessError:
        return False
    for img in json.loads(out or "[]"):
        for a in img.get("aliases") or []:
            if a.get("name") == alias:
                return True
    return False


def ensure_images(rebuild: bool = False) -> None:
    for alias, build_script in [
        (MYCELIUM_BASE_IMAGE, SIM_DIR / "image" / "build.sh"),
        (IPV8_BOOTSTRAP_IMAGE, SIM_DIR / "ipv8_bootstrap" / "build.sh"),
    ]:
        if rebuild and _lxc_image_exists(alias):
            _log(f"--rebuild-images: deleting stale {alias}...")
            subprocess.run(["lxc", "image", "delete", alias], check=True)
        if not _lxc_image_exists(alias):
            _log(f"building {alias} image (this can take a few minutes)...")
            subprocess.run([str(build_script)], check=True)
        else:
            _log(f"{alias} image already present")


def _lxc_instance(name: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["lxc", "list", name, "--format", "json"], text=True, timeout=10,
        )
    except subprocess.CalledProcessError:
        return None
    for inst in json.loads(out or "[]"):
        if inst.get("name") == name:
            return inst
    return None


def _lxc_ipv4(name: str) -> str:
    inst = _lxc_instance(name)
    if not inst:
        return ""
    eth0 = ((inst.get("state") or {}).get("network") or {}).get("eth0") or {}
    for addr in eth0.get("addresses", []):
        if addr.get("family") == "inet":
            return addr.get("address", "")
    return ""


def launch_ipv8_bootstrap(cfg: dict) -> str:
    _log("launching IPv8 bootstrap container...")
    # Always start fresh — a half-stuck container from a prior crashed run
    # carries no state worth keeping, and reusing one whose tracker died
    # mid-run hides the failure mode behind a successful-looking netstat.
    if _lxc_instance(IPV8_BOOTSTRAP_NAME) is not None:
        subprocess.run(
            ["lxc", "delete", "--force", IPV8_BOOTSTRAP_NAME],
            check=False, timeout=30,
        )
    subprocess.run(
        ["lxc", "launch", IPV8_BOOTSTRAP_IMAGE, IPV8_BOOTSTRAP_NAME],
        check=True, timeout=120,
    )
    deadline = time.time() + 30
    ip = ""
    while time.time() < deadline:
        ip = _lxc_ipv4(IPV8_BOOTSTRAP_NAME)
        if ip:
            break
        time.sleep(0.5)
    if not ip:
        raise RuntimeError("ipv8-bootstrap container never got an IPv4 within 30s")

    # Wait for openrc init to finish before kicking the tracker. Without this,
    # `lxc exec` lands in a half-booted container where backgrounded processes
    # get reaped before they bind — observed as `/root/logs/` missing entirely
    # after a "kick" that appeared to succeed at the host level. getty is the
    # last service alpine starts, so its presence means init is settled.
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["lxc", "exec", IPV8_BOOTSTRAP_NAME, "--", "pgrep", "-x", "getty"],
                check=False, timeout=5, capture_output=True,
            )
            if r.returncode == 0:
                break
        except Exception:
            pass
        time.sleep(0.5)

    # Image entrypoint isn't PID 1 (no openrc service for the tracker), so
    # `lxc start` leaves the tracker un-started. Mirror mock_sporestack's
    # mycelium boot pattern: detach via `lxc exec ... nohup &`. Re-kick every
    # iter until netstat confirms UDP/<port> is listening — once one tracker
    # binds, subsequent kicks fail at bind() and exit, harmless. busybox-alpine
    # ships `netstat`; iproute2's `ss` is not in the bootstrap image.
    bootstrap_port = cfg["network"]["ipv8_bootstrap_port"]
    kick_cmd = [
        "lxc", "exec", IPV8_BOOTSTRAP_NAME, "--",
        "sh", "-c",
        "mkdir -p /root/logs && "
        "nohup /usr/local/bin/ipv8-bootstrap-entrypoint "
        ">>/root/logs/tracker.log 2>&1 </dev/null &",
    ]
    probe_cmd = [
        "lxc", "exec", IPV8_BOOTSTRAP_NAME, "--",
        "sh", "-c", f"netstat -uln 2>/dev/null | grep -q ':{bootstrap_port} '",
    ]
    deadline = time.time() + 60
    last_kick_err = ""
    while time.time() < deadline:
        try:
            if subprocess.run(probe_cmd, timeout=5).returncode == 0:
                _log(f"ipv8-bootstrap up at {ip}, tracker listening on UDP {bootstrap_port}")
                return ip
            r = subprocess.run(
                kick_cmd, check=False, timeout=10,
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                last_kick_err = (r.stderr or r.stdout or "").strip()[:300] or f"rc={r.returncode}"
        except subprocess.TimeoutExpired:
            last_kick_err = "lxc exec kick timed out (LXD daemon slow?)"
        except Exception as e:
            last_kick_err = f"{type(e).__name__}: {e}"
        time.sleep(1)
    raise RuntimeError(
        f"ipv8-bootstrap tracker never started listening on {ip}:{bootstrap_port} — "
        f"last kick err: {last_kick_err!r}; "
        f"check `lxc exec {IPV8_BOOTSTRAP_NAME} -- cat /root/logs/tracker.log`"
    )


def create_fresh_genesis_wallet() -> tuple[BitcoinWallet, str]:
    SIM_HOME.mkdir(parents=True, exist_ok=True)
    db_path = SIM_HOME / "genesis_wallet.db"
    mnemonic_path = SIM_HOME / "genesis_mnemonic.txt"
    # Always start fresh — prior balance accumulates otherwise across re-runs
    db_path.unlink(missing_ok=True)
    mnemonic_path.unlink(missing_ok=True)
    db_uri = f"sqlite:///{db_path}"
    wallet = BitcoinWallet("mycelium-sim-genesis", network="regtest", db_uri=db_uri)
    mnemonic = wallet.create_new()
    mnemonic_path.write_text(mnemonic + "\n")
    os.chmod(mnemonic_path, 0o600)
    _log("created fresh genesis wallet")
    return wallet, mnemonic


def faucet_fund(address: str, btc: int) -> None:
    _log(f"faucet → {address} ({btc} BTC)...")
    subprocess.run(
        [str(SIM_DIR / "btc" / "faucet.py"), "send", address, str(btc)],
        check=True,
    )


def parse_bip21_amount_sat(payment_uri: str) -> int:
    if "?" not in payment_uri:
        raise ValueError(f"invoice payment_uri lacks query: {payment_uri}")
    query = payment_uri.split("?", 1)[1]
    for kv in query.split("&"):
        if kv.startswith("amount="):
            return int(round(float(kv[len("amount="):]) * 100_000_000))
    raise ValueError(f"invoice payment_uri lacks amount=: {payment_uri}")


def parse_bip21_address(payment_uri: str) -> str:
    return payment_uri[len("bitcoin:"):].split("?", 1)[0]


def fresh_regtest_sink_address() -> str:
    return subprocess.check_output(
        BCLI + ["getnewaddress"], text=True, timeout=10,
    ).strip()


def _scan_until_funded(wallet: BitcoinWallet, min_sat: int,
                       max_attempts: int = 20, delay: float = 3.0) -> None:
    """Poll until wallet has spendable UTXOs covering min_sat.

    Three things can lag here: electrs takes a beat to index the freshly mined
    faucet block; bitcoinlib's `wallet.scan()` populates the transactions table
    (which feeds `balance()`) before — sometimes well before — the UTXO table
    that `select_inputs()` actually reads from; and the underlying electrumx
    `address.listunspent` call can return empty even after `address.history`
    has reported the tx. Retrying on scan() exceptions or on balance alone is
    not enough — `wallet.send_to()` will still error with "No unspent
    transaction outputs found" if the UTXO table is empty.
    """
    inner = wallet.wallet
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            wallet.scan()
            inner.utxos_update(rescan_all=True)
            utxos = inner.utxos()
            spendable = sum(u.get("value", 0) for u in utxos)
            if utxos and spendable >= min_sat:
                if attempt > 0:
                    _log(f"wallet funded after {attempt + 1} scans: {len(utxos)} utxo(s), {spendable} sat")
                return
            _log(
                f"wallet has {len(utxos)} utxo(s) totalling {spendable} sat "
                f"(< required {min_sat}); scan {attempt + 1}/{max_attempts}, "
                f"retrying in {delay:.0f}s..."
            )
        except Exception as e:
            last_err = e
            _log(f"wallet.scan() attempt {attempt + 1}/{max_attempts} failed: {e}; retrying in {delay:.0f}s...")
        if attempt < max_attempts - 1:
            time.sleep(delay)
    if last_err is not None:
        raise last_err
    raise RuntimeError(
        f"wallet never reported spendable UTXOs ≥ {min_sat} sat after "
        f"{max_attempts} scans — is the faucet TX mined and electrs caught up?"
    )


def buy_genesis_server(wallet: BitcoinWallet, cfg: dict,
                       mock_sporestack_url: str) -> tuple[str, str]:
    """Quote → invoice → pay → poll credit → launch server. Returns (token, machine_id)."""
    days = cfg["genesis"]["days"]
    token = _http_get_text(f"{mock_sporestack_url}/token")
    _log(f"got token={token[:8]}..")

    quote = _http_get_json(f"{mock_sporestack_url}/server/quote?days={days}")
    cents = int(quote["cents"])
    dollars = math.ceil(cents / 100)
    _log(f"quote: {cents}c for {days} days → ${dollars} invoice")

    add = _http_post_json(
        f"{mock_sporestack_url}/token/{token}/add", {"dollars": dollars},
    )
    invoice = add["invoice"]
    pay_addr = parse_bip21_address(invoice["payment_uri"])
    amount_sat = parse_bip21_amount_sat(invoice["payment_uri"])
    _log(f"invoice: pay {amount_sat} sat to {pay_addr}")

    _scan_until_funded(wallet, amount_sat)
    txid = wallet.send(pay_addr, amount_sat)
    _log(f"sent {txid}")

    deadline = time.time() + 60
    while time.time() < deadline:
        info = _http_get_json(f"{mock_sporestack_url}/token/{token}/info")
        if info.get("balance_cents", 0) >= cents - 100:
            _log(f"token credited: balance_cents={info['balance_cents']}")
            break
        time.sleep(2)
    else:
        raise RuntimeError("token never credited within 60s")

    _, pub_key = generate_ssh_keypair(
        str(SIM_HOME / "genesis_ssh"), comment="mycelium-sim-genesis",
    )

    create = _http_post_json(
        f"{mock_sporestack_url}/token/{token}/servers",
        {
            "days": days,
            "flavor": "vps-1vcpu-1gb",
            "operating_system": "debian-12",
            "provider": "digitalocean",
            "region": "ams3",
            "billing_cycle": "monthly",
            "hostname": GENESIS_NAME,
            "ssh_key": pub_key,
        },
        timeout=120,
    )
    machine_id = create["machine_id"]
    _log(f"server provisioned: machine_id={machine_id}")
    return token, machine_id


def start_genesis_orchestrator(machine_id: str, token: str, mnemonic: str,
                               sink_address: str, cfg: dict,
                               mock_sporestack_url: str,
                               event_api_key: str) -> None:
    g = cfg["genesis"]
    env = {
        "MYCELIUM_FRIENDLY_NAME":          GENESIS_NAME,
        "MYCELIUM_PARENT_NAME":            GENESIS_NAME,
        "MYCELIUM_LOG_SECRET":             event_api_key,
        "MYCELIUM_SPORESTACK_TOKEN":       token,
        "MYCELIUM_CAUTION_TRAIT":          str(g["caution_trait"]),
        "MYCELIUM_CAUTION_MUTATION_SIGMA": str(g["caution_mutation_sigma"]),
        "MYCELIUM_SPAWN_THRESHOLD_DAYS":   str(g["spawn_threshold_days"]),
        "MYCELIUM_SPAWN_RESERVE_DAYS":     str(g["spawn_reserve_days"]),
        "MYCELIUM_INHERITANCE_RATIO":      str(g["inheritance_ratio"]),
        "MYCELIUM_DEFAULT_BTC_ADDRESS":    sink_address,
    }
    secrets = {
        "/root/data/btc_mnemonic_seed": mnemonic,
        "/root/data/sporestack_token":  token,
    }
    _log("posting /sim/start to mock SporeStack...")
    _http_post_json(
        f"{mock_sporestack_url}/sim/start/{machine_id}",
        {"env": env, "secrets": secrets},
        timeout=60,
    )
    _log("genesis orchestrator started")


def tail_genesis_logs(machine_id: str) -> None:
    _log(f"tailing /root/logs/orchestrator.log on {machine_id} (Ctrl+C to detach)...")

    def _on_sigint(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        subprocess.run([
            "lxc", "exec", machine_id, "--", "sh", "-c",
            "until [ -f /root/logs/orchestrator.log ]; do sleep 1; done; "
            "tail -f /root/logs/orchestrator.log",
        ])
    except KeyboardInterrupt:
        pass
    print()
    _log("detached from genesis log; sim still running. Use stop_simulation.sh to tear down.")


def main() -> None:
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Run the mycelium offline sim end-to-end.")
    parser.add_argument("--genesis-days", type=int, default=None,
                        help=f"Initial SporeStack runway for genesis (default from config: {cfg['genesis']['days']})")
    parser.add_argument("--genesis-btc", type=int, default=None,
                        help=f"Regtest BTC to faucet into genesis wallet (default from config: {cfg['genesis']['initial_btc']})")
    parser.add_argument("--time-scale", type=float, default=None,
                        help=f"Mock SporeStack time-scale multiplier (default from config: {cfg['sporestack']['time_scale']})")
    parser.add_argument("--no-tail", action="store_true",
                        help="Skip the trailing `lxc exec ... tail -f` step")
    parser.add_argument("--rebuild-images", action="store_true",
                        help="Delete and rebuild LXC images before starting")
    args = parser.parse_args()

    # CLI overrides win; config file is the default source of truth
    if args.genesis_days is not None:
        cfg["genesis"]["days"] = args.genesis_days
    if args.genesis_btc is not None:
        cfg["genesis"]["initial_btc"] = args.genesis_btc
    if args.time_scale is not None:
        cfg["sporestack"]["time_scale"] = args.time_scale

    net = cfg["network"]
    event_collector_url = f"http://127.0.0.1:{net['event_collector_port']}"
    mock_sporestack_url = f"http://127.0.0.1:{net['mock_sporestack_port']}"
    event_api_key = "123456789"

    preflight(cfg)
    start_btc_stack(cfg)
    start_event_collector(cfg)
    start_mock_sporestack(cfg)
    ensure_images(rebuild=args.rebuild_images)
    launch_ipv8_bootstrap(cfg)

    wallet, mnemonic = create_fresh_genesis_wallet()
    genesis_addr = wallet.get_receiving_address()
    faucet_fund(genesis_addr, cfg["genesis"]["initial_btc"])

    sink_addr = fresh_regtest_sink_address()
    _log(f"failsafe sink address: {sink_addr}")

    token, machine_id = buy_genesis_server(wallet, cfg, mock_sporestack_url)
    start_genesis_orchestrator(machine_id, token, mnemonic, sink_addr, cfg,
                               mock_sporestack_url, event_api_key)

    print()
    _log(f"sim up. genesis machine_id={machine_id}")
    _log(f"  events:  {SIM_DIR / 'data' / 'events.jsonl'}")
    _log(f"  mock:    {mock_sporestack_url}/healthz")
    _log(f"  collect: {event_collector_url}/healthz")
    print()

    if args.no_tail:
        return
    tail_genesis_logs(machine_id)


if __name__ == "__main__":
    main()

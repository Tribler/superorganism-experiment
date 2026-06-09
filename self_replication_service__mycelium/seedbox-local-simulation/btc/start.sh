#!/usr/bin/env bash
# Boot the regtest BTC stack (bitcoind + electrs + miner) for the offline sim.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BTC_DATADIR="${HOME}/.mycelium-sim/regtest"

# Preflight: required binaries.
for bin in bitcoind electrs bitcoin-cli; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "[start.sh] error: '$bin' not found in PATH" >&2
        exit 1
    fi
done

# Idempotent stop of any prior instances.
pkill -f 'bitcoind.*-regtest' || true
pkill -f 'electrs.*--network regtest' || true
pkill -f 'sim/btc/miner.py' || true
sleep 2

BCLI=(bitcoin-cli -regtest -datadir="${BTC_DATADIR}" -rpcuser=mycelium -rpcpassword=regtest -rpcconnect=127.0.0.1 -rpcport=18443)

# Start every sim run from a clean chain.
rm -rf "${BTC_DATADIR}"
mkdir -p "${BTC_DATADIR}"

# -minrelaytxfee=0/-blockmintxfee=0: bitcoinlib's auto-fee on regtest lands at
# the boundary; without this it gets "min relay fee not met" or stuck unbroadcast.
bitcoind -regtest -daemon -fallbackfee=0.0001 -minrelaytxfee=0 -blockmintxfee=0 -txindex \
    -datadir="${BTC_DATADIR}" \
    -rpcuser=mycelium -rpcpassword=regtest \
    -rpcbind=127.0.0.1:18443 -rpcallowip=127.0.0.1 \
    -rpcthreads=16 -rpcworkqueue=256

# Wait for RPC to come up.
for i in $(seq 1 30); do
    if "${BCLI[@]}" getblockchaininfo >/dev/null 2>&1; then break; fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "[start.sh] error: bitcoind RPC did not become ready in 30s" >&2
        exit 1
    fi
done

# Create-or-load wallet.
"${BCLI[@]}" createwallet mycelium-regtest 2>/dev/null \
    || "${BCLI[@]}" loadwallet mycelium-regtest 2>/dev/null \
    || true

# Pre-mine 101 blocks if needed (so coinbase matures).
height="$("${BCLI[@]}" getblockcount)"
if [ "${height}" -lt 101 ]; then
    addr="$("${BCLI[@]}" -rpcwallet=mycelium-regtest getnewaddress)"
    "${BCLI[@]}" generatetoaddress 101 "${addr}" >/dev/null
fi

# Launch electrs.
printf 'mycelium:regtest' >"${BTC_DATADIR}/electrs-auth"
chmod 600 "${BTC_DATADIR}/electrs-auth"
electrs --network regtest \
    --daemon-rpc-addr 127.0.0.1:18443 \
    --electrum-rpc-addr 0.0.0.0:60401 \
    --cookie-file "${BTC_DATADIR}/electrs-auth" \
    --db-dir "${BTC_DATADIR}/electrs-db" \
    --index-lookup-limit 1000 \
    --db-parallelism 8 \
    --log-filters WARN >"${BTC_DATADIR}/electrs.log" 2>&1 &
echo $! >"${BTC_DATADIR}/electrs.pid"
echo "[start.sh] waiting for electrs TCP port 60401..."
electrs_ready=0
for i in $(seq 1 30); do
    if nc -z 127.0.0.1 60401 2>/dev/null; then
        electrs_ready=1
        break
    fi
    if ! kill -0 "$(cat "${BTC_DATADIR}/electrs.pid")" 2>/dev/null; then
        echo "[start.sh] error: electrs died on startup; see ${BTC_DATADIR}/electrs.log" >&2
        exit 1
    fi
    sleep 1
done
if [ "${electrs_ready}" -eq 0 ]; then
    echo "[start.sh] error: electrs did not open TCP port within 30s; see ${BTC_DATADIR}/electrs.log" >&2
    exit 1
fi
echo "[start.sh] electrs is listening on 60401"

# Write bitcoinlib provider config.
python3 - <<'PY'
import json, os, pathlib
cfg_dir = pathlib.Path.home() / ".bitcoinlib"
cfg_dir.mkdir(parents=True, exist_ok=True)
cfg = cfg_dir / "providers.json"
data = {}
if cfg.exists():
    try:
        data = json.loads(cfg.read_text())
    except Exception:
        data = {}
data["electrum_regtest"] = {
    "provider": "electrumx",
    "network": "regtest",
    "client_class": "ElectrumxClient",
    "provider_coin_id": "",
    "url": "localhost:60401",
    "api_key": "",
    "priority": 11,
    "denominator": 100000000,
    "network_overrides": None,
}
tmp = cfg.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data, indent=2))
os.replace(tmp, cfg)
print("[start.sh] providers.json updated")
PY

# Launch miner daemon.
nohup python3 "${SCRIPT_DIR}/miner.py" >"${BTC_DATADIR}/miner.log" 2>&1 &
echo $! >"${BTC_DATADIR}/miner.pid"

# Final status.
echo "[start.sh] bitcoind RPC: 127.0.0.1:18443"
echo "[start.sh] electrs:      127.0.0.1:60401"
echo "[start.sh] block height: $("${BCLI[@]}" getblockcount)"
echo "[start.sh] balance:      $("${BCLI[@]}" -rpcwallet=mycelium-regtest getbalance) BTC"
echo "[start.sh] idle heartbeat: ${BTC_BLOCK_INTERVAL:-60}s (mempool txs mined within ~1s)"
echo "[start.sh] regtest stack ready"

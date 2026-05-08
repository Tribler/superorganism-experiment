#!/usr/bin/env bash
# Tear down the offline mycelium sim (TODO 8.10). Companion to run_simulation.py.
# No `set -e`: continue past failures so partial state still gets cleaned.
set -uo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNS_DIR="${SIM_DIR}/data/runs"
mkdir -p "${RUNS_DIR}"

# Archive events first — before kill, so an in-flight POST isn't lost.
# event_collector.py writes one events-<ts>.jsonl per spinup; move each into runs/ flat.
shopt -s nullglob
for f in "${SIM_DIR}/data/"events-*.jsonl; do
    mv "${f}" "${RUNS_DIR}/"
    echo "[stop_simulation] archived $(basename "${f}") to ${RUNS_DIR}/"
done
shopt -u nullglob

# Kill background processes (reverse startup order).
pkill -f mock_sporestack.py     || true
pkill -f event_collector.py     || true
pkill -f 'sim/btc/miner.py'     || true
pkill -f 'electrs --network regtest' || true
pkill -f 'bitcoind.*-regtest'   || true

# Delete provisioned LXC containers — mycelium nodes match m-<12hex>; plus the bootstrap.
# Images (mycelium-base, ipv8-bootstrap-base) are kept so re-runs stay fast.
for c in $(lxc list --format csv -c n 2>/dev/null | grep -E '^(m-[a-f0-9]+|ipv8-bootstrap)$' || true); do
    echo "[stop_simulation] deleting container ${c}"
    lxc delete --force "${c}" || true
done

echo "[stop_simulation] torn down."

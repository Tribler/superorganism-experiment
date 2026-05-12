#!/usr/bin/env python3
"""Regtest miner daemon: drains the mempool as fast as it fills, then falls
back to mining empty blocks every BTC_BLOCK_INTERVAL seconds so the chain
keeps progressing (electrs and time-scaling both depend on regular blocks)."""
import json
import os
import pathlib
import subprocess
import sys
import time

INTERVAL = float(os.getenv("BTC_BLOCK_INTERVAL", "5"))
BTC_DATADIR = pathlib.Path.home() / ".mycelium-sim" / "regtest"
BCLI = [
    "bitcoin-cli", "-regtest", f"-datadir={BTC_DATADIR}",
    "-rpcuser=mycelium", "-rpcpassword=regtest",
    "-rpcconnect=127.0.0.1", "-rpcport=18443",
]


def _cli(*args):
    result = subprocess.run(BCLI + list(args), check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _mempool_has_txs() -> bool:
    raw = _cli("getrawmempool")
    return bool(json.loads(raw or "[]"))


def main():
    coinbase = _cli("-rpcwallet=mycelium-regtest", "getnewaddress")
    print(f"[miner] mining to {coinbase}; drain on mempool, idle every {INTERVAL}s", flush=True)
    while True:
        try:
            mempool_busy = _mempool_has_txs()
            blockhash_json = _cli("generatetoaddress", "1", coinbase)
            print(
                f"[miner] mined {blockhash_json}"
                + (" (mempool drain)" if mempool_busy else ""),
                flush=True,
            )
            if mempool_busy:
                # Loop back immediately — keep draining until mempool is empty.
                continue
        except Exception as e:
            print(f"[miner] error: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

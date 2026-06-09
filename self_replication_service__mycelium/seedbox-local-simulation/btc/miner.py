#!/usr/bin/env python3
"""Regtest miner daemon: mines a block immediately whenever the mempool has
transactions (draining it as fast as it fills), and otherwise only mines a
single idle "heartbeat" block every BTC_BLOCK_INTERVAL seconds. Blocks are thus
proportional to activity rather than wall-clock time, so chain height and
coinbase history don't bloat the electrs index while the sim sits idle. A fresh
coinbase address is used per block so no single scripthash accrues unbounded
coinbase history. Set BTC_BLOCK_INTERVAL<=0 to disable idle blocks entirely."""
import json
import os
import pathlib
import subprocess
import sys
import time

# Idle heartbeat: seconds between blocks when the mempool is empty (<=0 disables
# idle mining). The mempool is polled every POLL_S so pending txs still confirm
# within ~1s regardless of the heartbeat length.
HEARTBEAT_S = float(os.getenv("BTC_BLOCK_INTERVAL", "60"))
POLL_S = 1.0
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


def _mine_block() -> str:
    # Rotate the coinbase address per block (like faucet.py / mock_sporestack.py)
    # so no single scripthash accrues unbounded coinbase history in electrs.
    addr = _cli("-rpcwallet=mycelium-regtest", "getnewaddress")
    return _cli("generatetoaddress", "1", addr)


def main():
    if HEARTBEAT_S > 0:
        print(f"[miner] drain on mempool; idle heartbeat every {HEARTBEAT_S}s", flush=True)
    else:
        print("[miner] drain on mempool; idle mining disabled", flush=True)
    last_block = time.monotonic()
    while True:
        try:
            if _mempool_has_txs():
                print(f"[miner] mined {_mine_block()} (mempool drain)", flush=True)
                last_block = time.monotonic()
                # Loop back immediately — keep draining until mempool is empty.
                continue
            if HEARTBEAT_S > 0 and time.monotonic() - last_block >= HEARTBEAT_S:
                print(f"[miner] mined {_mine_block()} (idle heartbeat)", flush=True)
                last_block = time.monotonic()
        except Exception as e:
            print(f"[miner] error: {e}", file=sys.stderr, flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()

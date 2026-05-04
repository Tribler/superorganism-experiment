#!/usr/bin/env python3
"""Regtest miner daemon: mines one block every BTC_BLOCK_INTERVAL seconds."""
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


def main():
    coinbase = _cli("-rpcwallet=mycelium-regtest", "getnewaddress")
    print(f"[miner] mining to {coinbase} every {INTERVAL}s", flush=True)
    while True:
        try:
            blockhash_json = _cli("generatetoaddress", "1", coinbase)
            print(f"[miner] mined {blockhash_json}", flush=True)
        except Exception as e:
            print(f"[miner] error: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

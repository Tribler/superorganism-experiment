#!/usr/bin/env python3
"""Regtest faucet: send coins from the mycelium-regtest wallet and confirm immediately."""
import argparse
import pathlib
import subprocess
import sys

BTC_DATADIR = pathlib.Path.home() / ".mycelium-sim" / "regtest"
BCLI = [
    "bitcoin-cli", "-regtest", f"-datadir={BTC_DATADIR}",
    "-rpcuser=mycelium", "-rpcpassword=regtest",
    "-rpcconnect=127.0.0.1", "-rpcport=18443",
    "-rpcwallet=mycelium-regtest",
]


def _cli(*args) -> str:
    result = subprocess.run(BCLI + list(args), check=True, capture_output=True, text=True)
    return result.stdout.strip()


def send(address: str, btc: str) -> str:
    txid = _cli("sendtoaddress", address, btc)
    coinbase = _cli("getnewaddress")
    _cli("generatetoaddress", "1", coinbase)
    return txid


def main():
    parser = argparse.ArgumentParser(description="Regtest faucet for the mycelium offline sim.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_send = sub.add_parser("send", help="Send BTC to an address and mine 1 confirmation block.")
    p_send.add_argument("address")
    p_send.add_argument("btc")
    args = parser.parse_args()

    if args.cmd == "send":
        try:
            print(send(args.address, args.btc))
        except subprocess.CalledProcessError as e:
            print(f"[faucet] bitcoin-cli failed: {e.stderr.strip()}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

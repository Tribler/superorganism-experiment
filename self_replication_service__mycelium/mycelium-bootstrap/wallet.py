#!/usr/bin/env python3
"""CLI wrapper for wallet operations."""

import logging
import sys

from lib.wallet import BitcoinWallet, create_wallet_interactive

logging.basicConfig(level=logging.INFO)

if len(sys.argv) < 2:
    print("Usage: python wallet.py <command> [args]")
    print("Commands:")
    print("  create <name>     - Create new wallet")
    print("  load <name>       - Load existing wallet")
    print("  balance <name>    - Check balance")
    print("  address <name>    - Get receiving address")
    print("  xpub <name>       - Get extended public key")
    print("  scan <name>       - Scan blockchain for updates")
    print("  interactive       - Interactive mode")
    sys.exit(1)

command = sys.argv[1]

if command == "interactive":
    wallet = create_wallet_interactive()
elif len(sys.argv) < 3:
    print(f"Command '{command}' requires wallet name")
    sys.exit(1)
else:
    wallet_name = sys.argv[2]
    wallet = BitcoinWallet(wallet_name)

    if command == "create":
        mnemonic = wallet.create_new()
        print(f"Mnemonic: {mnemonic}")
        print(f"Address: {wallet.get_receiving_address()}")
    elif command == "load":
        wallet.load()
        print(f"Loaded. Balance: {wallet.get_balance_btc()} BTC")
    elif command == "balance":
        wallet.load()
        print(f"Balance: {wallet.get_balance_btc()} BTC")
    elif command == "address":
        wallet.load()
        print(f"Address: {wallet.get_receiving_address()}")
        print(f"Network: Bitcoin (BTC)")
        print(f"Note: On Binance, select 'Bitcoin' or 'BTC' network (NOT BEP20/Lightning)")
    elif command == "xpub":
        wallet.load()
        print(f"xpub: {wallet.get_xpub()}")
    elif command == "scan":
        wallet.load()
        wallet.scan()
        print(f"Balance after scan: {wallet.get_balance_btc()} BTC")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

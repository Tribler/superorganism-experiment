import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

from healthchecker.gui import run_gui
from healthchecker.sampler import run
from healthchecker.liberation_service import LiberationService
from healthchecker.db import init_db


def main():
    parser = argparse.ArgumentParser(description="SwarmHealth - Creative Commons Torrent Health Checker")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to CSV file with magnet links (required for csv mode)"
    )
    parser.add_argument(
        "--mode",
        choices=["csv", "ipv8"],
        default="csv",
        help="Data source: csv (file) or ipv8 (network received content)"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Run with GUI (default: command line)"
    )
    parser.add_argument(
        "--liberation",
        action="store_true",
        help="Run Liberation Community service to gossip liberated content"
    )
    parser.add_argument(
        "--key-file",
        default=None,
        help="Path to key file for Liberation Community (default: liberation_key.pem)"
    )

    args = parser.parse_args()

    # Validate csv_path based on mode
    if args.mode == "csv":
        csv_path = Path(args.csv_path or "torrents_template.csv")
        if not csv_path.exists():
            print(f"Error: CSV file not found: {csv_path}")
            print("\nExpected CSV format:")
            print("url,license,magnet_link")
            print("https://example.com/content,CC-BY,magnet:?xt=urn:btih:...")
            sys.exit(1)
        csv_path_str = str(csv_path)
    else:
        # IPV8 mode - no CSV needed
        csv_path_str = args.csv_path

    if args.liberation:
        # Run Liberation Community service only (receive-only mode)
        liberation_csv = csv_path_str or "torrents.csv"
        asyncio.run(run_liberation_service_standalone(liberation_csv, args.key_file))
    elif args.mode == "ipv8":
        # IPV8 mode: start liberation service in background, then health checker
        run_ipv8_mode(args.gui, args.key_file)
    elif args.gui:
        run_gui(csv_path_str, mode=args.mode)
    else:
        run(csv_path=csv_path_str, mode=args.mode)


def run_liberation_in_thread(key_file: str = None):
    """Run the liberation service in a background thread with its own event loop."""
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        service = LiberationService(csv_path="/nonexistent/path.csv", key_file=key_file or "liberation_key.pem")
        try:
            loop.run_until_complete(service.start())
            loop.run_forever()
        except Exception as e:
            print(f"Liberation service error: {e}")
        finally:
            loop.run_until_complete(service.stop())
            loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def run_ipv8_mode(gui: bool = False, key_file: str = None):
    """Run health checker in IPV8 mode with liberation service in background."""
    print("Starting IPV8 mode...")
    print("  - Liberation service will receive content from peers")
    print("  - Health checker will sample from received content")
    print()

    # Initialize database first
    init_db()

    # Start liberation service in background
    print("Starting liberation service in background...")
    liberation_thread = run_liberation_in_thread(key_file)

    # Give the liberation service time to start and connect to peers
    print("Waiting for IPV8 network to initialize...")
    time.sleep(10)

    # Now start the health checker
    if gui:
        run_gui(csv_path=None, mode="ipv8")
    else:
        run(csv_path=None, mode="ipv8")


async def run_liberation_service_standalone(csv_path: str, key_file: str = None):
    """Run liberation service standalone (original --liberation behavior)."""
    from healthchecker.liberation_service import run_liberation_service
    await run_liberation_service(csv_path, key_file)


if __name__ == "__main__":
    main()
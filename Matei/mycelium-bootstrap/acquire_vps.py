#!/usr/bin/env python3
"""Acquire a VPS from SporeStack. Run once after funding."""

import argparse
import json
import logging
import sys
from pathlib import Path

from lib.deployer import generate_ssh_keypair
from lib.provisioner import SporeStackClient, SporeStackError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_SSH_KEY_DIR = Path.home() / ".mycelium" / "ssh"
DEFAULT_SSH_KEY_PATH = DEFAULT_SSH_KEY_DIR / "deploy_key"
TOKEN_FILE = Path.home() / ".mycelium" / "sporestack_token"
SERVER_INFO_FILE = Path.home() / ".mycelium" / "server.json"

# Defaults from SporeStackClient
DEFAULT_FLAVOR = SporeStackClient.DEFAULT_FLAVOR
DEFAULT_OS = SporeStackClient.DEFAULT_OS
DEFAULT_PROVIDER = SporeStackClient.DEFAULT_PROVIDER
DEFAULT_DAYS = SporeStackClient.DEFAULT_DAYS


def load_token() -> str | None:
    """Load SporeStack token from saved file."""
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        logger.info(f"Loaded token from {TOKEN_FILE}")
        return token
    return None


def get_or_create_ssh_key(key_path: Path) -> tuple[str, str]:
    """Get existing or create new SSH keypair."""
    pub_path = Path(f"{key_path}.pub")

    if key_path.exists() and pub_path.exists():
        logger.info(f"Using existing SSH key: {key_path}")
        with open(pub_path) as f:
            public_key = f.read().strip()
        return str(key_path), public_key

    logger.info(f"Generating new SSH keypair: {key_path}")
    return generate_ssh_keypair(str(key_path))


def save_server_info(info: dict) -> None:
    """Save server info for use by deploy_mycelium.py."""
    SERVER_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SERVER_INFO_FILE, "w") as f:
        json.dump(info, f, indent=2)
    logger.info(f"Server info saved to {SERVER_INFO_FILE}")


def acquire(
    token: str,
    flavor: str = DEFAULT_FLAVOR,
    operating_system: str = DEFAULT_OS,
    provider: str = DEFAULT_PROVIDER,
    days: int = DEFAULT_DAYS,
    hostname: str = "mycelium",
) -> dict:
    """Acquire a VPS from SporeStack."""
    private_key_path, public_key = get_or_create_ssh_key(DEFAULT_SSH_KEY_PATH)

    sporestack = SporeStackClient(token)

    # Check balance
    logger.info("Checking SporeStack balance...")
    balance = sporestack.get_balance()
    logger.info(f"Balance: {balance.get('usd', 'N/A')}")

    # Get quote
    quote = sporestack.get_quote(flavor, days, provider)
    logger.info(f"Server cost: {quote.get('usd', 'N/A')} for {days} days")

    # Launch server
    logger.info(f"Launching server: {hostname}")
    machine_id = sporestack.launch_server(
        flavor=flavor,
        ssh_key=public_key,
        operating_system=operating_system,
        provider=provider,
        days=days,
        hostname=hostname,
    )
    logger.info(f"Server launched: {machine_id}")

    # Wait for server to be ready
    logger.info("Waiting for server to be ready...")
    server = sporestack.wait_for_server_ready(machine_id, timeout=300)

    host = server["ipv4"]
    ssh_port = server.get("ssh_port", 22)
    logger.info(f"Server ready: {host}:{ssh_port}")

    # Save server info
    server_info = {
        "machine_id": machine_id,
        "ipv4": host,
        "ssh_port": ssh_port,
        "hostname": hostname,
        "provider": provider,
        "flavor": flavor,
        "operating_system": operating_system,
        "days": days,
        "ssh_key_path": private_key_path,
    }
    save_server_info(server_info)

    # Print success
    print()
    print("=" * 60)
    print("VPS ACQUIRED!")
    print("=" * 60)
    print(f"Machine ID: {machine_id}")
    print(f"IP Address: {host}")
    print(f"SSH: ssh -i {private_key_path} root@{host}")
    print()
    print("Next step: python deploy_mycelium.py")
    print("=" * 60)

    return server_info


def main():
    parser = argparse.ArgumentParser(
        description="Acquire a VPS from SporeStack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Run 'python fund_sporestack.py fund <amount>' first to fund your account.

After acquiring a VPS, run 'python deploy_mycelium.py' to deploy.
        """
    )

    parser.add_argument("--token", help="SporeStack token (auto-loaded from ~/.mycelium/sporestack_token)")
    parser.add_argument("--flavor", default=DEFAULT_FLAVOR, help=f"Server flavor (default: {DEFAULT_FLAVOR})")
    parser.add_argument("--os", dest="operating_system", default=DEFAULT_OS, help=f"Operating system (default: {DEFAULT_OS})")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help=f"VPS provider (default: {DEFAULT_PROVIDER})")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Server lifetime in days (default: {DEFAULT_DAYS})")
    parser.add_argument("--hostname", default="mycelium", help="Server hostname (default: mycelium)")
    parser.add_argument("--list-flavors", action="store_true", help="List available server flavors and exit")
    parser.add_argument("--list-os", action="store_true", help="List available operating systems and exit")

    args = parser.parse_args()

    # Handle list commands (don't need token)
    if args.list_flavors or args.list_os:
        client = SporeStackClient("dummy")
        if args.list_flavors:
            print("Available flavors:")
            for f in client.get_flavors():
                print(f"  {f.get('slug')}: {f.get('description', 'N/A')}")
        if args.list_os:
            print("Available operating systems:")
            for os_info in client.get_operating_systems():
                print(f"  {os_info.get('slug')}: {os_info.get('description', 'N/A')}")
        return

    # Load token
    token = args.token or load_token()
    if not token:
        logger.error("SporeStack token not found.")
        logger.error("Run 'python fund_sporestack.py' first to create and save token.")
        sys.exit(1)

    try:
        acquire(
            token=token,
            flavor=args.flavor,
            operating_system=args.operating_system,
            provider=args.provider,
            days=args.days,
            hostname=args.hostname,
        )
    except SporeStackError as e:
        logger.error(f"SporeStack error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

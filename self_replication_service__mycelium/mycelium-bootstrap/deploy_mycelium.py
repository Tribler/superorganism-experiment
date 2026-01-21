#!/usr/bin/env python3
"""Deploy mycelium to a VPS. Can be run multiple times for testing."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from lib.deployer import Deployer, DeployerError
from lib.wallet import BitcoinWallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SERVER_INFO_FILE = Path.home() / ".mycelium" / "server.json"
DEFAULT_SSH_KEY_PATH = Path.home() / ".mycelium" / "ssh" / "deploy_key"
DEFAULT_WALLET_NAME = "mycelium"
DEFAULT_CONTENT_DIR = Path(__file__).parent / "TestMusic"


def load_server_info() -> dict | None:
    """Load saved server info from file."""
    if not SERVER_INFO_FILE.exists():
        return None

    try:
        with open(SERVER_INFO_FILE) as f:
            info = json.load(f)
        logger.info(f"Loaded server info from {SERVER_INFO_FILE}")
        return info
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load server info: {e}")
        return None


def load_xpub(wallet_name: str = DEFAULT_WALLET_NAME) -> str | None:
    """Load xpub from local Bitcoin wallet."""
    wallet = BitcoinWallet(wallet_name)
    if not wallet.exists():
        return None
    wallet.load()
    return wallet.get_xpub()


def deploy(
    host: str,
    ssh_port: int = 22,
    ssh_key_path: str = None,
    content_dir: str = None,
    bitcoin_xpub: str = None,
) -> None:
    """Deploy mycelium to server."""
    key_path = ssh_key_path or str(DEFAULT_SSH_KEY_PATH)
    deployer = Deployer(key_path)

    try:
        logger.info(f"Connecting to {host}:{ssh_port}...")
        deployer.connect(host, port=ssh_port, retry_count=5, retry_delay=10)

        logger.info("Installing system dependencies...")
        deployer.install_dependencies()

        logger.info("Configuring firewall...")
        deployer.setup_firewall()

        logger.info("Deploying mycelium...")
        deployer.deploy_mycelium()

        if content_dir:
            logger.info(f"Uploading content from {content_dir}...")
            deployer.deploy_content(content_dir)

        logger.info("Starting orchestrator...")
        deployer.start_orchestrator(bitcoin_xpub=bitcoin_xpub)

        logger.info("Verifying health...")
        if deployer.check_health():
            logger.info("Orchestrator is running!")
        else:
            logger.warning("Health check failed - check logs below")

        print()
        print("=" * 60)
        print("DEPLOYMENT COMPLETE!")
        print("=" * 60)
        print(f"SSH: ssh -i {key_path} root@{host}")
        print()
        print("Streaming orchestrator logs (Ctrl+C to exit)...")
        print("=" * 60)
        print()

    except DeployerError as e:
        logger.error(f"Deployment error: {e}")
        raise
    finally:
        deployer.disconnect()

    # Stream logs - this replaces the Python process
    os.execvp("ssh", [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        f"root@{host}",
        "tail", "-f", "/root/logs/orchestrator.log"
    ])


def main():
    parser = argparse.ArgumentParser(
        description="Deploy mycelium to a VPS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Server info is loaded from ~/.mycelium/server.json (created by acquire_vps.py).
Use --host to override or deploy to any server.

Examples:
  python deploy_mycelium.py                     # Deploy to saved server
  python deploy_mycelium.py --host 95.179.1.1   # Deploy to specific IP
  python deploy_mycelium.py --no-content        # Skip content upload
        """
    )

    parser.add_argument("--host", help="Server IP address (overrides saved server info)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("--ssh-key", help=f"SSH key path (default: {DEFAULT_SSH_KEY_PATH})")
    parser.add_argument("--content-dir", help="Content directory to upload")
    parser.add_argument("--no-content", action="store_true", help="Skip content upload")
    parser.add_argument("--wallet", default=DEFAULT_WALLET_NAME, help=f"Wallet name for xpub (default: {DEFAULT_WALLET_NAME})")
    parser.add_argument("--no-xpub", action="store_true", help="Deploy without Bitcoin wallet")

    args = parser.parse_args()

    # Determine host
    host = args.host
    ssh_port = args.port
    ssh_key = args.ssh_key

    if not host:
        info = load_server_info()
        if info:
            host = info.get("ipv4") or info.get("host")
            ssh_port = info.get("ssh_port", ssh_port)
            ssh_key = ssh_key or info.get("ssh_key_path")
            logger.info(f"Using saved server: {host}:{ssh_port}")
        else:
            logger.error(f"No server info found at {SERVER_INFO_FILE}")
            logger.error("Run 'python acquire_vps.py' first, or specify --host")
            sys.exit(1)

    # Load xpub
    bitcoin_xpub = None
    if not args.no_xpub:
        bitcoin_xpub = load_xpub(args.wallet)
        if not bitcoin_xpub:
            logger.warning("No Bitcoin wallet found, deploying without xpub")

    # Determine content directory
    content_dir = args.content_dir
    if not content_dir and not args.no_content:
        if DEFAULT_CONTENT_DIR.exists():
            content_dir = str(DEFAULT_CONTENT_DIR)
            logger.info(f"Auto-detected content directory: {content_dir}")

    # Deploy
    try:
        deploy(
            host=host,
            ssh_port=ssh_port,
            ssh_key_path=ssh_key,
            content_dir=content_dir,
            bitcoin_xpub=bitcoin_xpub,
        )
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

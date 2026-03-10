#!/usr/bin/env python3
"""Deploy mycelium to a VPS. Can be run multiple times for testing."""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from lib.deployer import Deployer, DeployerError
from lib.wallet import BitcoinWallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SERVER_INFO_FILE = Path.home() / ".mycelium" / "server.json"
LOG_ENDPOINT_FILE = Path.home() / ".mycelium" / "log_endpoint"
LOG_SECRET_FILE = Path.home() / ".mycelium" / "log_secret"
DEFAULT_SSH_KEY_PATH = Path.home() / ".mycelium" / "ssh" / "deploy_key"
DEFAULT_VIDEO_IDS_FILE = Path(__file__).parent / "yt-api-cc-scripts" / "cc_video_ids.txt"
DEFAULT_COOKIES_FILE = Path(__file__).parent / "yt_cookies.txt"


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


def load_log_config() -> tuple[str | None, str | None]:
    endpoint = LOG_ENDPOINT_FILE.read_text().strip() if LOG_ENDPOINT_FILE.exists() else None
    secret = LOG_SECRET_FILE.read_text().strip() if LOG_SECRET_FILE.exists() else None
    if not endpoint:
        logger.warning("No log endpoint found at ~/.mycelium/log_endpoint, deploying without event logging")
    return endpoint, secret


def generate_vps_wallet() -> tuple[str, str]:
    """
    Generate a fresh ephemeral wallet for VPS injection.

    Returns (mnemonic, btc_address). The local wallet DB is deleted
    immediately after — only the mnemonic is handed to the VPS.
    """
    wallet = BitcoinWallet(f"vps-deploy-{int(time.time())}")
    mnemonic = wallet.create_new()
    address = wallet.get_receiving_address()
    wallet.delete()
    return mnemonic, address


def deploy(
    host: str,
    ssh_port: int = 22,
    ssh_key_path: str = None,
) -> None:
    """Deploy mycelium to server."""
    key_path = ssh_key_path or str(DEFAULT_SSH_KEY_PATH)
    deployer = Deployer(key_path)

    try:
        logger.info(f"Connecting to {host}:{ssh_port}...")
        deployer.connect(host, port=ssh_port, retry_count=5, retry_delay=10)

        if deployer.wallet_initialized():
            logger.info("Existing wallet on VPS — skipping wallet generation")
            print("\nExisting wallet detected. Keeping current VPS wallet.\n")
            btc_mnemonic = None
        else:
            btc_mnemonic, btc_address = generate_vps_wallet()
            print()
            print("=" * 60)
            print("Generated VPS btc wallet")
            print(f"Address : {btc_address}")
            print("=" * 60)
            print()

        logger.info("Installing system dependencies...")
        deployer.install_dependencies()

        logger.info("Configuring firewall...")
        deployer.setup_firewall()

        logger.info("Deploying mycelium...")
        deployer.deploy_mycelium()

        if DEFAULT_VIDEO_IDS_FILE.exists():
            logger.info(f"Uploading video IDs file...")
            deployer.deploy_video_ids(str(DEFAULT_VIDEO_IDS_FILE))
        else:
            logger.warning(f"Video IDs file not found at {DEFAULT_VIDEO_IDS_FILE}, skipping")

        if DEFAULT_COOKIES_FILE.exists():
            logger.info("Uploading YouTube cookies file...")
            deployer.deploy_cookies(str(DEFAULT_COOKIES_FILE))
        else:
            logger.warning(f"Cookies file not found at {DEFAULT_COOKIES_FILE}, content download may fail without auth")

        logger.info("Starting orchestrator...")
        log_endpoint, log_secret = load_log_config()
        deployer.start_orchestrator(btc_mnemonic=btc_mnemonic, log_endpoint=log_endpoint, log_secret=log_secret)

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
    known_hosts = str(Path.home() / ".mycelium" / "known_hosts")
    os.execvp("ssh", [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
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
        """
    )

    parser.add_argument("--host", help="Server IP address (overrides saved server info)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("--ssh-key", help=f"SSH key path (default: {DEFAULT_SSH_KEY_PATH})")

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

    # Deploy
    try:
        deploy(
            host=host,
            ssh_port=ssh_port,
            ssh_key_path=ssh_key,
        )
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

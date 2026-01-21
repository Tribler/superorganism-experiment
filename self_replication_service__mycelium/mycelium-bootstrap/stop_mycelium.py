#!/usr/bin/env python3
"""Stop mycelium orchestrator on the VPS to save resources during development."""

import json
import logging
import sys
from pathlib import Path

from lib.deployer import Deployer, DeployerError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SERVER_INFO_FILE = Path.home() / ".mycelium" / "server.json"
DEFAULT_SSH_KEY_PATH = Path.home() / ".mycelium" / "ssh" / "deploy_key"


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


def main():
    info = load_server_info()
    if not info:
        logger.error(f"No server info found at {SERVER_INFO_FILE}")
        logger.error("Run 'python acquire_vps.py' first")
        sys.exit(1)

    host = info.get("ipv4") or info.get("host")
    ssh_port = info.get("ssh_port", 22)
    ssh_key = info.get("ssh_key_path") or str(DEFAULT_SSH_KEY_PATH)

    deployer = Deployer(ssh_key)

    try:
        logger.info(f"Connecting to {host}:{ssh_port}...")
        deployer.connect(host, port=ssh_port)

        # Check if running
        if deployer.check_health():
            logger.info("Stopping mycelium orchestrator...")
            deployer.run_command("pkill -f 'python.*main.py'", check=False)

            # Verify stopped
            if not deployer.check_health():
                logger.info("Mycelium stopped successfully")
            else:
                logger.warning("Process may still be running")
        else:
            logger.info("Mycelium is not running")

    except DeployerError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        deployer.disconnect()


if __name__ == "__main__":
    main()

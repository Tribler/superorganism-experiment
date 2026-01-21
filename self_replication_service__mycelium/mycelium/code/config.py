"""
Configuration management for the autonomous orchestrator.

All configuration values are sourced from environment variables.
"""

import os
from pathlib import Path


class Config:
    """Central configuration for the orchestrator system."""

    # Repository
    REPO_URL: str = os.getenv(
        "MYCELIUM_REPO_URL",
        "https://github.com/Tribler/superorganism-experiment.git"
    )
    REPO_BRANCH: str = os.getenv("MYCELIUM_BRANCH", "main")

    # Timing
    UPDATE_CHECK_INTERVAL: int = int(os.getenv("MYCELIUM_UPDATE_INTERVAL", "60"))
    HEARTBEAT_INTERVAL: int = int(os.getenv("MYCELIUM_HEARTBEAT_INTERVAL", "60"))

    # Paths
    BASE_DIR: Path = Path(os.getenv("MYCELIUM_BASE_DIR", "/root/mycelium"))
    LOG_DIR: Path = Path(os.getenv("MYCELIUM_LOG_DIR", "/root/logs"))
    DATA_DIR: Path = Path(os.getenv("MYCELIUM_DATA_DIR", "/root/data"))
    CONTENT_DIR: Path = Path(os.getenv("MYCELIUM_CONTENT_DIR", "/root/music"))

    # Seedbox configuration
    TORRENT_TRACKER: str = os.getenv(
        "MYCELIUM_TRACKER",
        "udp://tracker.opentrackr.org:1337/announce"
    )
    SEEDBOX_PORT_MIN: int = int(os.getenv("MYCELIUM_SEEDBOX_PORT_MIN", "6881"))
    SEEDBOX_PORT_MAX: int = int(os.getenv("MYCELIUM_SEEDBOX_PORT_MAX", "6891"))
    SEEDBOX_STATUS_INTERVAL: int = int(os.getenv("MYCELIUM_SEEDBOX_STATUS_INTERVAL", "10"))

    # Logging configuration
    LOG_LEVEL: str = os.getenv("MYCELIUM_LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Bitcoin wallet configuration (watch-only)
    BITCOIN_WALLET_NAME: str = os.getenv("MYCELIUM_BITCOIN_WALLET", "mycelium_wallet")
    BITCOIN_XPUB: str = os.getenv("MYCELIUM_BITCOIN_XPUB", "")  # Extended public key only
    BITCOIN_NETWORK: str = os.getenv("MYCELIUM_BITCOIN_NETWORK", "bitcoin")  # mainnet

    # Exit codes
    EXIT_SUCCESS: int = 0
    EXIT_FAILURE: int = 1
    EXIT_RESTART: int = 42

    @classmethod
    def validate(cls) -> None:
        """Validate configuration and create necessary directories."""
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.CONTENT_DIR.mkdir(parents=True, exist_ok=True)

"""
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
    HEARTBEAT_INTERVAL: int = int(os.getenv("MYCELIUM_HEARTBEAT_INTERVAL", "300"))

    # Paths
    BASE_DIR: Path = Path(os.getenv("MYCELIUM_BASE_DIR", "/root/mycelium"))
    LOG_DIR: Path = Path(os.getenv("MYCELIUM_LOG_DIR", "/root/logs"))
    DATA_DIR: Path = Path(os.getenv("MYCELIUM_DATA_DIR", "/root/data"))
    CONTENT_DIR: Path = Path(os.getenv("MYCELIUM_CONTENT_DIR", "/root/music"))
    VIDEO_IDS_FILE: Path = Path(os.getenv("MYCELIUM_VIDEO_IDS_FILE", "/root/cc_video_ids.txt"))
    COOKIES_FILE: Path = Path(os.getenv("MYCELIUM_COOKIES_FILE", "/root/yt_cookies.txt"))
    DISK_THRESHOLD: int = int(os.getenv("MYCELIUM_DISK_THRESHOLD", "10"))

    # Node identity
    FRIENDLY_NAME: str = os.getenv("MYCELIUM_FRIENDLY_NAME", "mycelium-node")
    PUBLIC_IP: str = os.getenv("MYCELIUM_PUBLIC_IP", "")

    # Event logging
    LOG_ENDPOINT: str = os.getenv("MYCELIUM_LOG_ENDPOINT", "")
    LOG_SECRET: str = os.getenv("MYCELIUM_LOG_SECRET", "")
    PARENT_NAME: str = os.getenv("MYCELIUM_PARENT_NAME", "genesis")

    # IPV8 / Fleet
    WHOAMI_BROADCAST_INTERVAL: int = int(os.getenv("MYCELIUM_WHOAMI_BROADCAST_INTERVAL", "60"))
    WHOAMI_GOSSIP_COOLDOWN: int = int(os.getenv("MYCELIUM_WHOAMI_GOSSIP_COOLDOWN", "60"))
    PEER_REGISTRY_TTL: int = int(os.getenv("MYCELIUM_PEER_REGISTRY_TTL", "3600"))
    CONTENT_BROADCAST_INTERVAL: int = int(os.getenv("MYCELIUM_CONTENT_BROADCAST_INTERVAL", str(5 * 3600)))

    # Seedbox configuration
    TORRENT_TRACKER: str = os.getenv(
        "MYCELIUM_TRACKER",
        "udp://tracker.opentrackr.org:1337/announce"
    )
    SEEDBOX_PORT_MIN: int = int(os.getenv("MYCELIUM_SEEDBOX_PORT_MIN", "6881"))
    SEEDBOX_PORT_MAX: int = int(os.getenv("MYCELIUM_SEEDBOX_PORT_MAX", "6891"))
    SEEDBOX_STATUS_INTERVAL: int = int(os.getenv("MYCELIUM_SEEDBOX_STATUS_INTERVAL", "300"))

    # Logging configuration
    LOG_LEVEL: str = os.getenv("MYCELIUM_LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Bitcoin wallet configuration (spending wallet)
    BITCOIN_WALLET_NAME: str = os.getenv("MYCELIUM_BITCOIN_WALLET", "mycelium_wallet")
    BTC_MNEMONIC: str = os.getenv("MYCELIUM_BTC_MNEMONIC", "")
    BITCOIN_NETWORK: str = os.getenv("MYCELIUM_BITCOIN_NETWORK", "bitcoin")  # mainnet
    DEFAULT_BTC_ADDRESS: str = os.getenv("MYCELIUM_DEFAULT_BTC_ADDRESS", "")

    # Persistent state
    STATE_DB_FILE: Path = DATA_DIR / "state.db"
    INITIAL_CAUTION_TRAIT: float = float(os.getenv("MYCELIUM_CAUTION_TRAIT", "0.5"))

    # Caution trait mutation (injected by deployer at birth — same for genesis and children)
    CAUTION_MUTATION_SIGMA: float = float(os.getenv("MYCELIUM_CAUTION_MUTATION_SIGMA", "0.05"))
    CAUTION_TRAIT_MIN: float      = float(os.getenv("MYCELIUM_CAUTION_TRAIT_MIN", "0.1"))
    CAUTION_TRAIT_MAX: float      = float(os.getenv("MYCELIUM_CAUTION_TRAIT_MAX", "0.9"))

    # Spawn thresholds (injected by deployer; caution=0 baseline values)
    SPAWN_THRESHOLD_DAYS: int  = int(os.getenv("MYCELIUM_SPAWN_THRESHOLD_DAYS", "60"))
    SPAWN_RESERVE_DAYS: int    = int(os.getenv("MYCELIUM_SPAWN_RESERVE_DAYS", "30"))
    INHERITANCE_RATIO: float   = float(os.getenv("MYCELIUM_INHERITANCE_RATIO", "0.4"))

    # Decision loop
    DECISION_INTERVAL: int     = int(os.getenv("MYCELIUM_DECISION_INTERVAL", "21600")) #6h
    FAILSAFE_TRIGGER_DAYS: int = int(os.getenv("MYCELIUM_FAILSAFE_TRIGGER_DAYS", "2"))
    TOPUP_TRIGGER_DAYS: int    = int(os.getenv("MYCELIUM_TOPUP_TRIGGER_DAYS", "30"))
    TOPUP_TARGET_DAYS: int     = int(os.getenv("MYCELIUM_TOPUP_TARGET_DAYS", "30"))

    # Max seconds the shutdown handler will defer a signal while a spawn is in progress.
    # After this, SIGTERM/SIGINT is honoured so operator can kill a bricked spawn
    MAX_SPAWN_DURATION: int = int(os.getenv("MYCELIUM_MAX_SPAWN_DURATION", str(2 * 3600)))  # 2h

    # SporeStack / VPS identity
    SPORESTACK_TOKEN_FILE: Path = DATA_DIR / "sporestack_token"
    SPORESTACK_BASE_URL: str = os.getenv("MYCELIUM_SPORESTACK_BASE_URL", "https://api.sporestack.com").rstrip("/")

    # Sim-mode overrides (production: all unset → no behavioural change)
    # Comma-separated host:port list; when set, replaces ipv8 default_bootstrap_defs.
    # Critical safety rail in sim: prevents fallback to Tribler defaults, which would
    # let sim nodes discover real swarm peers (LiberationCommunity ID is shared with prod).
    IPV8_BOOTSTRAP: str = os.getenv("MYCELIUM_IPV8_BOOTSTRAP", "")
    SIM_MODE: bool = os.getenv("MYCELIUM_SIM_MODE", "").strip().lower() in ("1", "true", "yes")

    # SporeStack / VPS provisioning defaults (injected by deployer; mirror mycelium-bootstrap/config.json)
    VPS_PROVIDER: str      = os.getenv("MYCELIUM_VPS_PROVIDER", "sporestack_eu")
    VPS_FLAVOR: str        = os.getenv("MYCELIUM_VPS_FLAVOR", "sporestack-eu-4gb")
    VPS_REGION: str        = os.getenv("MYCELIUM_VPS_REGION", "amsterdam")
    VPS_OS: str            = os.getenv("MYCELIUM_VPS_OS", "ubuntu-24.04")
    VPS_DAYS: int          = int(os.getenv("MYCELIUM_VPS_DAYS", "30"))
    VPS_BILLING_CYCLE: str = os.getenv("MYCELIUM_VPS_BILLING_CYCLE", "monthly")
    # Fallback monthly VPS cost in cents. Used when SporeStack's /server/quote is still not available.
    VPS_MONTHLY_COST_CENTS: int = int(os.getenv("MYCELIUM_VPS_MONTHLY_COST_CENTS", "3000"))

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

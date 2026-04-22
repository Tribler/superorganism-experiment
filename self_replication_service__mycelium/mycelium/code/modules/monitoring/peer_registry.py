"""
Tracks SeedboxInfoPayload messages from other nodes.
Maintains an in-memory dict of known peers, with lazy staleness filtering.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from ipv8.peer import Peer

from ..seeding.liberation_community import SeedboxInfoPayload
from utils import setup_logger
from config import Config

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


@dataclass
class PeerInfo:
    peer_mid: str
    friendly_name: str
    public_ip: str
    git_commit_hash: str
    uptime_seconds: int
    disk_total_bytes: int
    disk_used_bytes: int
    btc_address: str
    btc_balance_sat: int
    vps_provider_region: str
    vps_days_remaining: int
    last_seen: float  # Unix timestamp


class PeerRegistry:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._fleet: Dict[str, PeerInfo] = {}
        self._ttl = ttl_seconds

    def on_seedbox_info_received(self, peer: Peer, payload: SeedboxInfoPayload) -> None:
        """Callback wired to LiberationCommunity. Updates fleet entry for this peer."""
        key = payload.btc_address  # identity = BTC public key, stable across relays
        self._fleet[key] = PeerInfo(
            peer_mid=peer.mid.hex(),  # immediate sender (may be a relay); kept for debug
            friendly_name=payload.friendly_name,
            public_ip=payload.public_ip,
            git_commit_hash=payload.git_commit_hash,
            uptime_seconds=payload.uptime_seconds,
            disk_total_bytes=payload.disk_total_bytes,
            disk_used_bytes=payload.disk_used_bytes,
            btc_address=payload.btc_address,
            btc_balance_sat=payload.btc_balance_sat,
            vps_provider_region=payload.vps_provider_region,
            vps_days_remaining=payload.vps_days_remaining,
            last_seen=time.time(),
        )
        logger.info("Fleet updated: %s (%d sat, %d days remaining)",
                    payload.friendly_name, payload.btc_balance_sat, payload.vps_days_remaining)

    def get_live_peers(self) -> List[PeerInfo]:
        """Return peers heard from within the TTL window."""
        cutoff = time.time() - self._ttl
        return [p for p in self._fleet.values() if p.last_seen >= cutoff]

    def get_peer_count(self) -> int:
        return len(self.get_live_peers())

    def get_all_peers(self) -> List[PeerInfo]:
        """All peers including stale (for debugging/heartbeat logging)."""
        return list(self._fleet.values())


_registry: Optional[PeerRegistry] = None


def init(ttl_seconds: int = 3600) -> PeerRegistry:
    global _registry
    _registry = PeerRegistry(ttl_seconds)
    return _registry


def get_registry() -> Optional[PeerRegistry]:
    return _registry

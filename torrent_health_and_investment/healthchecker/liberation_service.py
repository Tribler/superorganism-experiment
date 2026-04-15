import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Set

from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8_service import IPv8

from healthchecker.liberation_community import LiberationCommunity, LiberatedContentPayload, SeedboxInfoPayload
from ipv8.peer import Peer


class LiberationService:
    """
    Receive-only IPv8 service. Joins the Liberation Community, receives liberated
    content from peers, persists it to the database, and tracks seedbox fleet info.
    """

    def __init__(self, key_file: Optional[str] = None):
        self.key_file = key_file or "liberation_key.pem"
        self.community: Optional[LiberationCommunity] = None
        self.ipv8: Optional[IPv8] = None

        # Track received infohashes to avoid processing duplicates
        self.received_content: Set[str] = set()

        # In-memory seedbox fleet info: peer_mid hex -> {payload fields + last_seen}
        self.seedbox_fleet: Dict[str, dict] = {}

    async def start(self) -> None:
        from healthchecker.db import get_all_received_infohashes
        self.received_content = get_all_received_infohashes()
        print(f"Loaded {len(self.received_content)} previously received entries from database")

        builder = ConfigBuilder().clear_keys().clear_overlays()

        key_path = Path(self.key_file)
        if key_path.exists():
            print(f"Using existing key: {key_path}")
        else:
            print(f"Creating new key: {key_path}")
        builder.add_key("liberation_peer", "medium", str(key_path))

        builder.add_overlay(
            "LiberationCommunity",
            "liberation_peer",
            [WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
            default_bootstrap_defs,
            {},
            [("started",)]
        )

        configuration = builder.finalize()
        self.ipv8 = IPv8(
            configuration,
            extra_communities={"LiberationCommunity": LiberationCommunity}
        )

        await self.ipv8.start()
        print("IPv8 started")

        for overlay in self.ipv8.overlays:
            if isinstance(overlay, LiberationCommunity):
                self.community = overlay
                break

        if not self.community:
            raise RuntimeError("LiberationCommunity not found after startup")

        print("LiberationCommunity is running")
        print(f"Community ID: {self.community.community_id.hex()}")
        print(f"My peer ID: {self.community.my_peer.mid.hex()[:16]}...")

        self.community.set_content_received_callback(self.on_content_received)
        self.community.set_seedbox_info_callback(self.on_seedbox_info_received)

        print(f"Connected to {len(self.community.get_peers())} peer(s)")

    def on_content_received(self, from_peer: Peer, payload: LiberatedContentPayload) -> None:
        infohash = self._extract_infohash(payload.magnet_link)
        if not infohash:
            print(f"[WARN] Received invalid magnet link from peer {from_peer.mid.hex()[:16]}")
            return

        if infohash in self.received_content:
            return

        self.received_content.add(infohash)

        from healthchecker.db import insert_received_content
        success = insert_received_content(
            infohash=infohash,
            url=payload.url,
            license=payload.license,
            magnet_link=payload.magnet_link,
            received_at=payload.timestamp,
            source_peer=from_peer.mid.hex()[:16]
        )


    def on_seedbox_info_received(self, from_peer: Peer, payload: SeedboxInfoPayload) -> None:
        peer_mid = from_peer.mid.hex()[:16]
        self.seedbox_fleet[peer_mid] = {
            "friendly_name": payload.friendly_name,
            "public_ip": payload.public_ip,
            "git_commit_hash": payload.git_commit_hash,
            "uptime_seconds": payload.uptime_seconds,
            "disk_total_bytes": payload.disk_total_bytes,
            "disk_used_bytes": payload.disk_used_bytes,
            "btc_address": payload.btc_address,
            "btc_balance_sat": payload.btc_balance_sat,
            "vps_provider_region": payload.vps_provider_region,
            "vps_days_remaining": payload.vps_days_remaining,
            "last_seen": int(time.time()),
        }
    def _extract_infohash(self, magnet_link: str) -> Optional[str]:
        try:
            parts = magnet_link.split("btih:")
            if len(parts) > 1:
                return parts[1].split("&")[0]
        except Exception:
            pass
        return None

    async def stop(self) -> None:
        if self.ipv8:
            await self.ipv8.stop()
            print("Liberation service stopped")

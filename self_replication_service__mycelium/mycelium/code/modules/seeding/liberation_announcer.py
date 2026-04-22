"""
Liberation Announcer - broadcasts seeded content to IPV8 network.

This module connects the seedbox to the IPV8 network, announcing
all seeded torrents so health checkers can discover and monitor them.
"""

import asyncio
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import aiohttp
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8_service import IPv8

from config import Config
from utils import setup_logger
from .liberation_community import LiberationCommunity, LiberatedContentPayload, SeedboxInfoPayload
from .seedbox import Seedbox, ContentInfo
from ..core.wallet import get_wallet
from ..monitoring.node_monitor import get_monitor
from ..monitoring.peer_registry import get_registry

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class LiberationAnnouncer:
    """
    Announces seeded content to the IPV8 network.
    """

    def __init__(self, seedbox: Seedbox, key_file: Optional[str] = None):
        self.seedbox = seedbox
        self.key_file = key_file or str(Config.DATA_DIR / "liberation_key.pem")
        self.ipv8: Optional[IPv8] = None
        self.community: Optional[LiberationCommunity] = None

        # Seedbox info
        self._start_time: float = time.time()
        self._cached_public_ip: Optional[str] = None

    async def start(self) -> None:
        """Start the IPV8 service and liberation community."""
        logger.info("Starting Liberation Announcer...")

        builder = ConfigBuilder().clear_keys().clear_overlays()

        key_path = Path(self.key_file)
        if key_path.exists():
            logger.info("Using existing key: %s", key_path)
        else:
            logger.info("Creating new key: %s", key_path)

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
        logger.info("IPv8 started")

        # Find the liberation community
        for overlay in self.ipv8.overlays:
            if isinstance(overlay, LiberationCommunity):
                self.community = overlay
                break

        if not self.community:
            raise RuntimeError("LiberationCommunity not found after startup")

        registry = get_registry()
        if registry:
            self.community.set_seedbox_info_callback(registry.on_seedbox_info_received)
            logger.info("Peer registry wired to seedbox info callback")

        self.community.set_new_peer_callback(self._send_all_content_to_peer)
        logger.info("New-peer content burst callback registered")

        logger.info("LiberationCommunity is running")
        logger.info("Community ID: %s", self.community.community_id.hex())
        logger.info("My peer ID: %s...", self.community.my_peer.mid.hex()[:16])

    async def announce_content(self) -> int:
        """
        Announce all seeded content to the network.

        Returns:
            Number of peers reached across all content items
        """
        if not self.community:
            logger.warning("Cannot announce: community not initialized")
            return 0

        content_list = self.seedbox.get_content_for_broadcast()
        total_sent = 0

        for content in content_list:
            payload = LiberatedContentPayload(
                url=content.url or "",
                license=content.license or "Creative Commons",
                magnet_link=content.magnet_link,
                timestamp=int(time.time())
            )
            total_sent += self.community.broadcast_content(payload)

        return total_sent

    async def announce_loop(self, interval: int = Config.CONTENT_BROADCAST_INTERVAL) -> None:
        """
        Periodically broadcast the full content list to all peers.

        Args:
            interval: Seconds between full-broadcast cycles
        """
        logger.info("Starting announcement loop (interval: %ds)", interval)

        while True:
            try:
                # Wait for peers to connect
                await asyncio.sleep(5)

                peer_count = len(self.community.get_peers()) if self.community else 0
                logger.info("Connected to %d peer(s)", peer_count)

                if peer_count > 0:
                    sent_count = await self.announce_content()
                    logger.info("Full periodic broadcast: %d payload(s) sent across all peers", sent_count)

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                logger.info("Announcement loop cancelled")
                break
            except Exception as e:
                logger.error("Error in announcement loop: %s", e)
                await asyncio.sleep(interval)

    async def _send_all_content_to_peer(self, peer) -> None:
        """Send full content list to a newly connected peer."""
        if not self.community:
            return
        content_list = self.seedbox.get_content_for_broadcast()
        for content in content_list:
            payload = LiberatedContentPayload(
                url=content.url or "",
                license=content.license or "Creative Commons",
                magnet_link=content.magnet_link,
                timestamp=int(time.time()),
            )
            try:
                self.community.ez_send(peer, payload)
            except Exception as e:
                logger.warning("Failed initial burst to peer %s: %s", peer.mid.hex()[:16], e)
        logger.info("Initial burst: %d items → new peer %s", len(content_list), peer.mid.hex()[:16])

    def _get_git_commit_hash(self) -> str:
        """Get short git commit hash of the running code."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Config.BASE_DIR)
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    async def _get_public_ip(self) -> str:
        """Get public IP: from config if set, else auto-discover via ipify (cached)."""
        if Config.PUBLIC_IP:
            return Config.PUBLIC_IP
        if self._cached_public_ip:
            return self._cached_public_ip
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.ipify.org", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._cached_public_ip = await resp.text()
                        return self._cached_public_ip
        except Exception as e:
            logger.warning("Failed to auto-discover public IP: %s", e)
        return ""

    def _get_disk_usage(self) -> tuple[int, int]:
        """Get disk total and used bytes for /."""
        usage = shutil.disk_usage("/")
        return usage.total, usage.used

    async def _create_seedbox_info_payload(self) -> SeedboxInfoPayload:
        """Assemble a SeedboxInfoPayload with current node info."""
        uptime = int(time.time() - self._start_time)
        disk_total, disk_used = self._get_disk_usage()
        public_ip = await self._get_public_ip()

        w = get_wallet()
        btc_address = w.get_receiving_address() if w else ""
        state = get_monitor().get_state() if get_monitor() else None

        return SeedboxInfoPayload(
            friendly_name=Config.FRIENDLY_NAME,
            public_ip=public_ip,
            git_commit_hash=self._get_git_commit_hash(),
            uptime_seconds=uptime,
            disk_total_bytes=disk_total,
            disk_used_bytes=disk_used,
            btc_address=btc_address,
            btc_balance_sat=state.btc_balance_sat if state else 0,
            vps_provider_region=f"{state.vps_provider}/{state.vps_region}" if state else "",
            vps_days_remaining=state.days_remaining if state else 0,
        )

    async def announce_seedbox_info(self) -> int:
        """Broadcast seedbox info to all peers."""
        if not self.community:
            logger.warning("Cannot announce seedbox info: community not initialized")
            return 0

        payload = await self._create_seedbox_info_payload()
        return self.community.broadcast_seedbox_info(payload)

    async def seedbox_info_loop(self, interval: int = 60) -> None:
        """Periodically broadcast seedbox info."""
        logger.info("Starting seedbox info loop (interval: %ds)", interval)

        while True:
            try:
                peer_count = len(self.community.get_peers()) if self.community else 0
                if peer_count > 0:
                    sent = await self.announce_seedbox_info()
                    if sent > 0:
                        logger.info("Seedbox info sent to %d peer(s)", sent)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Seedbox info loop cancelled")
                break
            except Exception as e:
                logger.error("Error in seedbox info loop: %s", e)
                await asyncio.sleep(interval)

    def _extract_infohash(self, magnet_link: str) -> Optional[str]:
        """Extract infohash from magnet link."""
        try:
            parts = magnet_link.split("btih:")
            if len(parts) > 1:
                return parts[1].split("&")[0]
        except Exception:
            pass
        return None

    async def stop(self) -> None:
        """Stop the IPV8 service."""
        if self.ipv8:
            await self.ipv8.stop()
            logger.info("Liberation Announcer stopped")

    def get_stats(self) -> dict:
        """Get announcer statistics."""
        return {
            "connected_peers": len(self.community.get_peers()) if self.community else 0,
            "community_active": self.community is not None
        }

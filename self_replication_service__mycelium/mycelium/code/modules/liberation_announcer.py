"""
Liberation Announcer - broadcasts seeded content to IPV8 network.

This module connects the seedbox to the IPV8 network, announcing
all seeded torrents so health checkers can discover and monitor them.
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Set

from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8_service import IPv8

from config import Config
from utils import setup_logger
from modules.liberation_community import LiberationCommunity, LiberatedContentPayload
from modules.seedbox import Seedbox, ContentInfo

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class LiberationAnnouncer:
    """
    Announces seeded content to the IPV8 network.

    Works alongside the Seedbox to broadcast torrent information
    to health checkers on the network.
    """

    def __init__(self, seedbox: Seedbox, key_file: Optional[str] = None):
        self.seedbox = seedbox
        self.key_file = key_file or str(Config.DATA_DIR / "liberation_key.pem")
        self.ipv8: Optional[IPv8] = None
        self.community: Optional[LiberationCommunity] = None

        # Track announced content to avoid duplicates
        self.announced_infohashes: Set[str] = set()

    async def start(self) -> None:
        """Start the IPV8 service and liberation community."""
        logger.info("Starting Liberation Announcer...")

        builder = ConfigBuilder().clear_keys().clear_overlays()

        key_path = Path(self.key_file)
        if key_path.exists():
            logger.info(f"Using existing key: {key_path}")
        else:
            logger.info(f"Creating new key: {key_path}")

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

        logger.info("LiberationCommunity is running")
        logger.info(f"Community ID: {self.community.community_id.hex()}")
        logger.info(f"My peer ID: {self.community.my_peer.mid.hex()[:16]}...")

    async def announce_content(self) -> int:
        """
        Announce all seeded content to the network.

        Returns:
            Number of new content items announced
        """
        if not self.community:
            logger.warning("Cannot announce: community not initialized")
            return 0

        content_list = self.seedbox.get_content_for_broadcast()
        new_announcements = 0

        for content in content_list:
            # Extract infohash from magnet link
            infohash = self._extract_infohash(content.magnet_link)
            if not infohash:
                continue

            # Skip if already announced
            if infohash in self.announced_infohashes:
                continue

            # Create payload
            payload = LiberatedContentPayload(
                url=content.url or "",
                license=content.license or "Creative Commons",
                magnet_link=content.magnet_link,
                timestamp=int(time.time())
            )

            # Broadcast to peers
            sent_count = self.community.broadcast_content(payload, infohash)

            if sent_count > 0:
                self.announced_infohashes.add(infohash)
                new_announcements += 1
                logger.info(f"Announced: {content.file_path.name} to {sent_count} peers")

        return new_announcements

    async def announce_loop(self, interval: int = 30) -> None:
        """
        Continuously announce content at regular intervals.

        Args:
            interval: Seconds between announcement cycles
        """
        logger.info(f"Starting announcement loop (interval: {interval}s)")

        while True:
            try:
                # Wait for peers to connect
                await asyncio.sleep(5)

                peer_count = len(self.community.get_peers()) if self.community else 0
                logger.info(f"Connected to {peer_count} peer(s)")

                if peer_count > 0:
                    new_count = await self.announce_content()
                    if new_count > 0:
                        logger.info(f"Announced {new_count} new content items")

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                logger.info("Announcement loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in announcement loop: {e}")
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
            "announced_content": len(self.announced_infohashes),
            "connected_peers": len(self.community.get_peers()) if self.community else 0,
            "community_active": self.community is not None
        }

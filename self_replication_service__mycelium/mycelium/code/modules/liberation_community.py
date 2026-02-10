"""
IPV8 Liberation Community for announcing seeded content.

This community allows seedboxes to broadcast their torrents to the network,
enabling health checkers to discover and monitor them.
"""

from dataclasses import dataclass
from hashlib import sha1
from typing import Callable, Dict, Optional, Set

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer


@dataclass
class LiberatedContentPayload(DataClassPayload[1]):
    """Payload for announcing liberated content."""
    url: str
    license: str
    magnet_link: str
    timestamp: int  # Unix timestamp when content was liberated


@dataclass
class SeedboxInfoPayload(DataClassPayload[2]):
    """Payload for broadcasting seedbox fleet info."""
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


class LiberationCommunity(Community):
    """
    IPV8 community for announcing and discovering liberated content.

    Seedboxes broadcast their torrents to this community.
    Health checkers listen and monitor the announced torrents.
    """

    # Same community ID as SwarmHealth-Checker to enable discovery
    community_id = sha1(b"liberation_community").digest()

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)

        # Track which peers we've sent each infohash to
        self.sent_to_peers: Dict[bytes, Set[str]] = {}

        # Callback for received content (optional)
        self.on_content_received_callback: Optional[Callable[[Peer, LiberatedContentPayload], None]] = None

        # Callback for received seedbox info (optional)
        self.on_seedbox_info_callback: Optional[Callable[[Peer, SeedboxInfoPayload], None]] = None

        # Register message handlers
        self.add_message_handler(LiberatedContentPayload, self.on_liberated_content)
        self.add_message_handler(SeedboxInfoPayload, self.on_seedbox_info)

        self.logger.info("LiberationCommunity initialized (peer mid: %s)",
                        self.my_peer.mid.hex()[:16])

    def started(self) -> None:
        self.logger.info("LiberationCommunity started")

    def broadcast_content(self, payload: LiberatedContentPayload, infohash: str) -> int:
        """
        Broadcast content to all connected peers.

        Args:
            payload: The content payload to broadcast
            infohash: The torrent infohash (for dedup tracking)

        Returns:
            Number of peers the content was sent to
        """
        peers = self.get_peers()

        if not peers:
            self.logger.debug("No peers available to broadcast to")
            return 0

        broadcast_count = 0
        for peer in peers:
            # Initialize peer tracking if needed
            if peer.mid not in self.sent_to_peers:
                self.sent_to_peers[peer.mid] = set()

            # Only send if we haven't sent this to this peer before
            if infohash not in self.sent_to_peers[peer.mid]:
                try:
                    self.ez_send(peer, payload)
                    self.sent_to_peers[peer.mid].add(infohash)
                    broadcast_count += 1
                    self.logger.debug("Broadcasted to peer %s", peer.mid.hex()[:16])
                except Exception as e:
                    self.logger.warning("Failed to send to peer %s: %s",
                                       peer.mid.hex()[:16], e)

        if broadcast_count > 0:
            self.logger.info("Broadcasted content to %d peer(s)", broadcast_count)

        return broadcast_count

    @lazy_wrapper(LiberatedContentPayload)
    def on_liberated_content(self, peer: Peer, payload: LiberatedContentPayload) -> None:
        """Handle received liberated content."""
        self.logger.info("Received content from peer %s: %s",
                        peer.mid.hex()[:16], payload.url[:60] if payload.url else "unknown")

        if self.on_content_received_callback:
            try:
                self.on_content_received_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in content received callback: %s", e)

    def set_content_received_callback(
        self,
        callback: Callable[[Peer, LiberatedContentPayload], None]
    ) -> None:
        """Set callback for when content is received from peers."""
        self.on_content_received_callback = callback

    def broadcast_seedbox_info(self, payload: SeedboxInfoPayload) -> int:
        """
        Broadcast seedbox info to all connected peers (no dedup, latest wins).

        Returns:
            Number of peers the info was sent to
        """
        peers = self.get_peers()

        if not peers:
            self.logger.debug("No peers available to broadcast seedbox info to")
            return 0

        sent_count = 0
        for peer in peers:
            try:
                self.ez_send(peer, payload)
                sent_count += 1
            except Exception as e:
                self.logger.warning("Failed to send seedbox info to peer %s: %s",
                                   peer.mid.hex()[:16], e)

        if sent_count > 0:
            self.logger.info("Broadcasted seedbox info to %d peer(s)", sent_count)

        return sent_count

    @lazy_wrapper(SeedboxInfoPayload)
    def on_seedbox_info(self, peer: Peer, payload: SeedboxInfoPayload) -> None:
        """Handle received seedbox info."""
        self.logger.info("Received seedbox info from peer %s: %s",
                        peer.mid.hex()[:16], payload.friendly_name)

        if self.on_seedbox_info_callback:
            try:
                self.on_seedbox_info_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in seedbox info callback: %s", e)

    def set_seedbox_info_callback(
        self,
        callback: Callable[[Peer, SeedboxInfoPayload], None]
    ) -> None:
        """Set callback for when seedbox info is received from peers."""
        self.on_seedbox_info_callback = callback

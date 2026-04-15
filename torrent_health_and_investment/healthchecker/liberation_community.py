from dataclasses import dataclass
from typing import Callable, Dict, Optional, Set
from collections import defaultdict
from hashlib import sha1

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload, convert_to_payload
from ipv8.peer import Peer

@dataclass
class LiberatedContentPayload(DataClassPayload[1]):
    url: str
    license: str
    magnet_link: str
    timestamp: int  # Unix timestamp when content was liberated

convert_to_payload(LiberatedContentPayload, msg_id=1)


@dataclass
class SeedboxInfoPayload(DataClassPayload[2]):
    """Payload for receiving seedbox fleet info."""
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

convert_to_payload(SeedboxInfoPayload, msg_id=2)


class LiberationCommunitySettings(CommunitySettings):
    pass


class LiberationCommunity(Community):

    community_id = sha1(b"liberation_community").digest()

    def __init__(self, settings: LiberationCommunitySettings) -> None:
        super().__init__(settings)

        # Track which peers we've gossiped each infohash to (avoid re-sending)
        self.sent_to_peers: Dict[bytes, Set[str]] = defaultdict(set)

        # Register message handlers
        self.add_message_handler(LiberatedContentPayload, self.on_liberated_content)
        self.add_message_handler(SeedboxInfoPayload, self.on_seedbox_info)

        self.on_content_received_callback: Optional[Callable[[Peer, LiberatedContentPayload], None]] = None
        self.on_seedbox_info_callback: Optional[Callable[[Peer, SeedboxInfoPayload], None]] = None

        self.logger.info("LiberationCommunity initialized (peer mid: %s)",
                         self.my_peer.mid.hex()[:16])

    def started(self) -> None:
        self.logger.info("LiberationCommunity started")

    @lazy_wrapper(LiberatedContentPayload)
    def on_liberated_content(self, peer: Peer, payload: LiberatedContentPayload) -> None:
        if self.on_content_received_callback:
            try:
                self.on_content_received_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in content received callback: %s", e)

        # Extract infohash for deduplication
        try:
            infohash = payload.magnet_link.split("btih:")[1].split("&")[0]
        except (IndexError, AttributeError):
            infohash = None

        # Gossip to other peers (except the sender)
        other_peers = [p for p in self.get_peers() if p.mid != peer.mid]
        for other_peer in other_peers:
            if infohash and infohash in self.sent_to_peers[other_peer.mid]:
                continue
            try:
                self.ez_send(other_peer, payload)
                if infohash:
                    self.sent_to_peers[other_peer.mid].add(infohash)
                self.logger.debug("Gossiped to peer %s", other_peer.mid.hex()[:16])
            except Exception as e:
                self.logger.warning("Failed to gossip to peer %s: %s",
                                    other_peer.mid.hex()[:16], e)

    def set_content_received_callback(self, callback: Callable[[Peer, LiberatedContentPayload], None]) -> None:
        self.on_content_received_callback = callback

    @lazy_wrapper(SeedboxInfoPayload)
    def on_seedbox_info(self, peer: Peer, payload: SeedboxInfoPayload) -> None:
        if self.on_seedbox_info_callback:
            try:
                self.on_seedbox_info_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in seedbox info callback: %s", e)

    def set_seedbox_info_callback(
        self,
        callback: Callable[[Peer, SeedboxInfoPayload], None]
    ) -> None:
        self.on_seedbox_info_callback = callback

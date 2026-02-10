import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict
from hashlib import sha1

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer

@dataclass
class LiberatedContentPayload(DataClassPayload[1]):
    url: str
    license: str
    magnet_link: str
    timestamp: int  # Unix timestamp when content was liberated


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


class LiberationCommunitySettings(CommunitySettings):
    pass


class LiberationCommunity(Community):
    
    community_id = sha1(b"liberation_community").digest()
    
    def __init__(self, settings: LiberationCommunitySettings) -> None:
        super().__init__(settings)

        # Callback for tracking duplicate peers (set by service)
        # Signature: (peer: bytes, infohash: str) -> None
        self.duplicate_peers_callback: Optional[Callable[[bytes, str], None]] = None
        
        # Register message handlers
        self.add_message_handler(LiberatedContentPayload, self.on_liberated_content)
        self.add_message_handler(SeedboxInfoPayload, self.on_seedbox_info)

        # Callback for when new content is received (for future seeding integration)
        # Signature: (payload: LiberatedContentPayload) -> None
        self.on_content_received_callback: Optional[Callable[[Peer, LiberatedContentPayload], None]] = None

        # Callback for received seedbox info
        self.on_seedbox_info_callback: Optional[Callable[[Peer, SeedboxInfoPayload], None]] = None
        
        self.logger.info("LiberationCommunity initialized (peer mid: %s)",
                        self.my_peer.mid.hex()[:16])
    
    def started(self) -> None:
        self.logger.info("LiberationCommunity started")
    
    def broadcast_liberated_content(self, payload: LiberatedContentPayload, duplicate_peers: Dict[bytes, Set[str]], infohash: str) -> bool:
        peers = self.get_peers()
        
        if not peers:
            self.logger.debug("No peers available to broadcast to")
            return False
        
        broadcast_count = 0
        for peer in peers:
            if infohash not in duplicate_peers[peer.mid]:
                try:
                    self.ez_send(peer, payload)

                    if self.duplicate_peers_callback:
                        try:
                            self.duplicate_peers_callback(peer.mid, infohash)
                        except Exception as e:
                            self.logger.warning("Error in duplicate_peers_callback: %s", e)
                    broadcast_count += 1
                    self.logger.debug("Broadcasted to peer %s", peer.mid.hex()[:16])
                except Exception as e:
                    self.logger.warning("Failed to send to peer %s: %s", peer.mid.hex()[:16], e)
        
        if broadcast_count > 0:
            self.logger.info("Broadcasted liberated content to %d peer(s)", broadcast_count)
            return True
        
        return False
    
    @lazy_wrapper(LiberatedContentPayload)
    def on_liberated_content(self, peer: Peer, payload: LiberatedContentPayload) -> None:
        self.logger.info("Received commmunication from peer %s", peer.mid.hex()[:16])
        print(f"Payload: {payload}")

        if self.on_content_received_callback:
            try:
                self.on_content_received_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in content received callback: %s", e)
        
        # Gossip to other peers (except the sender)
        other_peers = [p for p in self.get_peers() if p.mid != peer.mid]
        for other_peer in other_peers:
            # Only send if we haven't sent this to this peer before
            if infohash not in self.sent_to_peers[other_peer.mid]:
                try:
                    self.ez_send(other_peer, payload)
                    self.sent_to_peers[other_peer.mid].add(infohash)
                    self.logger.debug("Gossiped to peer %s", other_peer.mid.hex()[:16])
                except Exception as e:
                    self.logger.warning("Failed to gossip to peer %s: %s", 
                                      other_peer.mid.hex()[:16], e)
    
    def get_liberated_content(self, infohash: Optional[str] = None) -> List[LiberatedContentPayload]:
        if infohash:
            if infohash in self.liberated_content:
                return [self.liberated_content[infohash]]
            return []
        return list(self.liberated_content.values())
    
    def set_content_received_callback(self, callback: Callable[[Peer, LiberatedContentPayload], None]) -> None:
        self.on_content_received_callback = callback

    def set_duplicate_peers_callback(self, callback: Callable[[bytes, str], None]) -> None:
        self.duplicate_peers_callback = callback

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


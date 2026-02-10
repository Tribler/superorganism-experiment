import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Set
from collections import defaultdict

from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.util import run_forever
from ipv8_service import IPv8
from ipv8.taskmanager import TaskManager
from ipv8.peer import Peer

from healthchecker.liberation_community import LiberationCommunity, LiberatedContentPayload, SeedboxInfoPayload
from healthchecker.csv_loader import CSVTorrentLoader, TorrentEntry


class LiberationService:
    """
    Service that runs the Liberation Community and broadcasts liberated content.
    """
    
    def __init__(self, csv_path: str, key_file: Optional[str] = None):
        self.csv_path = Path(csv_path)
        self.key_file = key_file or "liberation_key.pem"
        self.csv_loader = CSVTorrentLoader(str(csv_path))
        self.community: Optional[LiberationCommunity] = None
        self.ipv8: Optional[IPv8] = None

        # Registry of liberated content
        # Key: infohash (from magnet link), Value: LiberatedContentPayload
        self.liberated_content: Dict[str, LiberatedContentPayload] = {}

        # Track which peers we've sent content to (to avoid duplicates)
        # Key: peer mid, Value: set of infohashes we've sent
        self.sent_to_peers: Dict[bytes, Set[str]] = defaultdict(set)

        # Track received content by infohash to avoid processing duplicates
        self.received_content: Set[str] = set()

        # In-memory seedbox fleet info: peer_mid hex -> {payload fields + last_seen}
        self.seedbox_fleet: Dict[str, dict] = {}


    async def start(self) -> None:
        # Initialize database and load previously received content
        from healthchecker.db import init_db, get_all_received_infohashes
        init_db()
        self.received_content = get_all_received_infohashes()
        print(f"Loaded {len(self.received_content)} previously received entries from database")

        # Load CSV entries if available (for broadcasting)
        if self.csv_path.exists():
            print("Loading Creative Commons entries from CSV...")
            count = self.csv_loader.load()
            print(f"Loaded {count} total entries, {len(self.csv_loader.entries)} Creative Commons entries")
        else:
            print(f"No CSV file at {self.csv_path} - running in receive-only mode")

        builder = ConfigBuilder().clear_keys().clear_overlays()
        
        key_path = Path(self.key_file)
        if key_path.exists():
            print(f"Using existing key: {key_path}")
            builder.add_key("liberation_peer", "medium", str(key_path))
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

        self.community.set_duplicate_peers_callback(self.add_duplicate_peers)
        self.community.set_content_received_callback(self.on_content_received)
        self.community.set_seedbox_info_callback(self.on_seedbox_info_received)
        
        self.task_manager = TaskManager()

        self.task_manager.register_task("Broadcast Liberated Content", self.broadcast_liberated_content_loop, delay=10, interval=30)

        self.task_manager.register_task("Broadcast Liberated Content to new peers", self.broadcast_liberated_content_new_peers_loop, delay=30, interval=30)
        
        await self.task_manager.register_anonymous_task("take 5 seconds", time.sleep, 5)
        print(f"Connected to {len(self.community.get_peers())} peer(s)")

    def add_duplicate_peers(self, peer: bytes, infohash: str) -> None:
        self.sent_to_peers[peer].add(infohash)

    async def broadcast_liberated_content_loop(self) -> None:
        try:
            # Skip if no CSV loaded (receive-only mode)
            if not hasattr(self.csv_loader, 'entries') or not self.csv_loader.entries:
                peer_count = len(self.community.get_peers())
                print(f"\nStats: receive-only mode, {peer_count} peer(s), {len(self.received_content)} received")
                return

            entries = [
                entry for entry in self.csv_loader.entries
                if entry.magnet_link and entry.infohash
            ]

            if not entries:
                print("No Creative Commons entries with magnet links to broadcast")
                return
            
            new_entries = [
                entry for entry in entries
                if entry.infohash not in self.liberated_content
            ]
            
            if new_entries:
                print(f"\nBroadcasting {len(new_entries)} new liberated content entries...")
                for entry in new_entries:
                    payload = LiberatedContentPayload(
                        url=entry.url,
                        license=entry.license,
                        magnet_link=entry.magnet_link,
                        timestamp=int(time.time())
                    )
                    success = self.community.broadcast_liberated_content(payload, self.sent_to_peers, entry.infohash)
                    
                    if success:
                        self.liberated_content[entry.infohash] = payload
                        print(f"Broadcasted: {entry.url[:60]}...")
                    else:
                        print(f"Failed to broadcast: {entry.url[:60]}...")
            
            content_count = len(self.liberated_content)
            peer_count = len(self.community.get_peers())
            print(f"\nStats: {content_count} liberated content items, {peer_count} peer(s)")
            
        except Exception as e:
            print(f"Error in broadcast loop: {e}")
            import traceback
            traceback.print_exc()

    async def broadcast_liberated_content_new_peers_loop(self) -> None:
        try:
            if self.community.get_peers():
                import random
                sample_size = min(5, len(self.liberated_content))
                if sample_size > 0:
                    sample_infohashes = random.sample(list(self.liberated_content), sample_size)
                    for infohash in sample_infohashes:
                        payload = self.liberated_content[infohash]
                        if payload:
                            success = self.community.broadcast_liberated_content(payload, self.sent_to_peers, infohash)

                            if success:
                                print(f"Broadcasted to new peers: {payload.url[:60]}...")
                            else:
                                print(f"Failed to broadcast to new peers: {payload.url[:60]}...")
        
        except Exception as e:
            print(f"Error in broadcast loop: {e}")
            import traceback
            traceback.print_exc()
    
    def on_content_received(self, from_peer: Peer, payload: LiberatedContentPayload) -> None:
        # Extract infohash
        infohash = self._extract_infohash(payload.magnet_link)
        if not infohash:
            print(f"[WARN] Received invalid magnet link from peer {from_peer.mid.hex()[:16]}")
            return

        # Check if we've already received this content (in-memory cache)
        if infohash in self.received_content:
            return

        # Add to memory cache
        self.received_content.add(infohash)
        self.liberated_content[infohash] = payload

        # Persist to database
        from healthchecker.db import insert_received_content
        success = insert_received_content(
            infohash=infohash,
            url=payload.url,
            license=payload.license,
            magnet_link=payload.magnet_link,
            received_at=payload.timestamp,
            source_peer=from_peer.mid.hex()[:16]
        )

        if success:
            print(f"[RECEIVED] {payload.url[:60]}...")
            print(f"           License: {payload.license}")
            print(f"           Infohash: {infohash[:16]}...")
        else:
            print(f"[DUPLICATE] Already in database: {infohash[:16]}...")

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
        print(f"[SEEDBOX] Updated fleet info from {payload.friendly_name} ({peer_mid})")

    def _extract_infohash(self, magnet_link: str) -> Optional[str]:
        try:
            # magnet:?xt=urn:btih:INFOHASH
            parts = magnet_link.split("btih:")
            if len(parts) > 1:
                infohash = parts[1].split("&")[0]
                return infohash
        except Exception:
            pass
        return None
    
    async def stop(self) -> None:
        """Stop the IPv8 service."""
        if self.ipv8:
            await self.ipv8.stop()
            print("Liberation service stopped")


async def run_liberation_service(csv_path: str, key_file: Optional[str] = None) -> None:
    service = LiberationService(csv_path, key_file)
    
    try:
        await service.start()
        print("\n" + "="*60)
        print("Liberation Service is running!")
        print("="*60)
        print("The service will:")
        print("  - Broadcast liberated Creative Commons content")
        print("  - Receive and gossip content from other peers")
        print("  - Maintain a registry of known liberated content")
        print("\nPress Ctrl+C to stop")
        print("="*60 + "\n")
        
        await run_forever()
    except KeyboardInterrupt:
        print("\n\nStopping liberation service...")
    finally:
        await service.stop()


if __name__ == "__main__":
    import sys
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "torrents.csv"
    asyncio.run(run_liberation_service(csv_path))



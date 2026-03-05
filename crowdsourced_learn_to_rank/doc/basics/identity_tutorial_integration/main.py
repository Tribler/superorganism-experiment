import os
import types
from asyncio import run, sleep
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import libtorrent as lt

from ipv8.community import Community, CommunitySettings
from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, default_bootstrap_defs
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer
from ipv8.util import run_forever
from ipv8_service import IPv8

# Constants
CLOCK_THRESHOLD = 1000
SEEDER_PORT = 8090
BT_SEEDER_PORT = 6882
BT_DOWNLOADER_PORT = 6881
DOWNLOAD_TIMEOUT = 60
PEER_DISCOVERY_WAIT = 5
SOURCE_FILE_NAME = "Community2.py"
SOURCE_FILE_PATH = Path(__file__).parent / "source" / SOURCE_FILE_NAME

# Logging setup
LOG_FILE = Path(__file__).parent / "dynamic_loading.log"

def log(message: str) -> None:
    """Log message with timestamp to file."""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S.%f")[:-3] + "]"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    print(message)


def get_download_state(status) -> str:
    """Get human-readable download state."""
    states = ['queued', 'checking', 'downloading metadata',
              'downloading', 'finished', 'seeding',
              'allocating', 'checking fastresume']
    return states[status.state]


@dataclass
class MyMessage(DataClassPayload[1]):  # The value 1 identifies this message and must be unique per community
    clock: int  # We add an integer (technically a "long long") field "clock" to this message


@dataclass
class MagnetLinkMessage(DataClassPayload[2]):  # Message ID 2 for magnet links
    magnet_uri: str  # The magnet link URI
    seeder_host: str  # IP of seeder
    seeder_port: int  # BitTorrent port of seeder


class MyCommunity(Community):
    community_id = os.urandom(20)

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)
        # Register the message handler for messages (with the identifier "1").
        self.add_message_handler(MyMessage, self.on_message)
        self.add_message_handler(MagnetLinkMessage, self.on_magnet_link)
        # The Lamport clock this peer maintains.
        # This is for the example of global clock synchronization.
        self.lamport_clock = 0
        self.lt_session = None  # BitTorrent session

    def started(self) -> None:
        async def start_communication() -> None:
            if not self.lamport_clock:
                # If we have not started counting, try boostrapping
                # communication with our other known peers.
                for p in self.get_peers():
                    self.ez_send(p, MyMessage(self.lamport_clock))
            else:
                self.cancel_pending_task("start_communication")

        # We register an asyncio task with this overlay.
        # This makes sure that the task ends when this overlay is unloaded.
        # We call the "start_communication" function every 5.0 seconds, starting now.
        self.register_task("start_communication", start_communication, interval=5.0, delay=0)

    @lazy_wrapper(MyMessage)
    def on_message(self, peer: Peer, payload: MyMessage) -> None:
        # Update our Lamport clock.
        self.lamport_clock = max(self.lamport_clock, payload.clock) + 1
        print(self.my_peer, "current clock:", self.lamport_clock)

        # Torrent seeding: when clock reaches threshold, only seeder peer sends magnet link
        if self.lamport_clock >= CLOCK_THRESHOLD and not hasattr(self, '_seeding'):
            self._seeding = True
            if self.my_peer.address[1] == SEEDER_PORT:
                log(f"\n[PEER {self.my_peer.address[1]}] Clock reached {self.lamport_clock}, sending magnet link...")
                self.register_anonymous_task("send_magnet", self.send_magnet_to_peers)

        # Then synchronize with the rest of the network again.
        self.ez_send(peer, MyMessage(self.lamport_clock))

    async def send_magnet_to_peers(self) -> None:
        """Create torrent, seed, and send magnet link to all peers."""
        try:
            # Create torrent and start seeding
            magnet_uri = self.create_torrent_and_seed(SOURCE_FILE_PATH, BT_SEEDER_PORT)

            # Give seeder a moment to fully initialize
            await sleep(0.5)

            log(f"{'='*70}")
            log(f"=== SENDING MAGNET LINK VIA IPv8 NETWORK ===")
            log(f"=== FROM: Peer 1 -> TO: Peer 2 ===")
            log(f"{'='*70}")

            # Send magnet link to all peers
            peers = self.get_peers()
            log(f"[DEBUG] Found {len(peers)} peers to send to")

            for peer in peers:
                try:
                    log(f"[DEBUG] Attempting to send to {peer}")
                    self.ez_send(peer, MagnetLinkMessage(magnet_uri, "127.0.0.1", BT_SEEDER_PORT))
                    log(f"[SENT] Magnet link transmitted to {peer}")
                except Exception as e:
                    log(f"[ERROR] Failed to send magnet link to {peer}: {e}")
                    import traceback
                    log(f"[ERROR] Traceback: {traceback.format_exc()}")
        except Exception as e:
            log(f"[FATAL ERROR] send_magnet_to_peers crashed: {e}")
            import traceback
            log(f"[FATAL ERROR] Traceback: {traceback.format_exc()}")

    def _create_torrent_metadata(self, file_path: Path) -> lt.torrent_info:
        """Create torrent metadata for a file."""
        fs = lt.file_storage()
        lt.add_files(fs, str(file_path))
        tor = lt.create_torrent(fs)
        tor.set_creator("py-ipv8 dynamic loader")
        tor.add_tracker("udp://tracker.opentrackr.org:1337/announce")
        lt.set_piece_hashes(tor, str(file_path.parent))
        return lt.torrent_info(lt.bencode(tor.generate()))

    def create_torrent_and_seed(self, file_path: Path, port: int) -> str:
        """Create torrent for file and start seeding. Returns magnet URI."""
        log(f"{'='*70}")
        log(f"=== CREATING TORRENT FOR {file_path.name} ===")
        log(f"{'='*70}")

        # Create torrent metadata
        torrent_info = self._create_torrent_metadata(file_path)

        # Generate magnet URI
        info_hash = torrent_info.info_hashes().v1
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn={file_path.name}"
        log(f"Magnet URI: {magnet_uri}")

        # Start seeding
        log(f"[SEEDER] Starting to seed {file_path.name} on port {port}...")
        self.lt_session = lt.session({'listen_interfaces': f'0.0.0.0:{port}'})
        params = {'ti': torrent_info, 'save_path': str(file_path.parent)}
        self.lt_session.add_torrent(params)
        log(f"[SEEDER] Seeding on port {port}, ready to serve!")

        return magnet_uri

    @lazy_wrapper(MagnetLinkMessage)
    def on_magnet_link(self, peer: Peer, payload: MagnetLinkMessage) -> None:
        log(f"{'='*70}")
        log(f"[RECEIVED] Magnet link from {peer}")
        log(f"  URI: {payload.magnet_uri}")
        log(f"  Seeder: {payload.seeder_host}:{payload.seeder_port}")
        log(f"{'='*70}")
        self.register_anonymous_task("download_torrent",
                                     self.download_and_hotswap,
                                     payload.magnet_uri,
                                     payload.seeder_host,
                                     payload.seeder_port)

    async def download_and_hotswap(self, magnet_uri: str, seeder_host: str, seeder_port: int) -> None:
        """Download code via BitTorrent and perform hot-swap."""
        try:
            log(f"[DOWNLOAD] Starting BitTorrent download from {seeder_host}:{seeder_port}")

            # Initialize libtorrent
            self.lt_session = lt.session({'listen_interfaces': f'0.0.0.0:{BT_DOWNLOADER_PORT}'})
            log(f"[DOWNLOAD] Libtorrent session initialized")

            # Parse magnet and add torrent
            log(f"[DOWNLOAD] Parsing magnet URI...")
            params = lt.parse_magnet_uri(magnet_uri)
            params.save_path = str(Path(__file__).parent)

            log(f"[DOWNLOAD] Adding torrent to session...")
            handle = self.lt_session.add_torrent(params)
            log(f"[DOWNLOAD] Torrent added successfully")

            # Connect to seeder
            log(f"[DOWNLOAD] Connecting to seeder at {seeder_host}:{seeder_port}")
            handle.connect_peer((seeder_host, seeder_port))
            log(f"[DOWNLOAD] Connected to seeder")

            # Wait for download with timeout
            iterations = 0
            while not handle.is_seed() and iterations < DOWNLOAD_TIMEOUT:
                status = handle.status()
                state_str = get_download_state(status)
                log(f"[DOWNLOAD] Progress: {status.progress * 100:.2f}% | State: {state_str} | Peers: {status.num_peers} | Downloaded: {status.total_done} bytes")

                # Check if download is complete even if not seeding
                if status.is_finished or status.progress >= 1.0:
                    log(f"[DOWNLOAD] Download finished!")
                    break

                await sleep(1)
                iterations += 1

            if iterations >= DOWNLOAD_TIMEOUT:
                log(f"[DOWNLOAD] Timeout after {DOWNLOAD_TIMEOUT} seconds")
                return

            log(f"[DOWNLOAD] Download complete!")

            # Get downloaded file path
            file_path = Path(__file__).parent / SOURCE_FILE_NAME

            # Perform hot-swap
            await self.perform_hotswap(file_path)
        except Exception as e:
            log(f"[DOWNLOAD ERROR] Failed: {e}")
            import traceback
            log(f"[DOWNLOAD ERROR] Traceback: {traceback.format_exc()}")

    async def perform_hotswap(self, file_path: Path) -> None:
        """Hot-swap the on_message method with code from file."""
        log(f"{'='*70}")
        log(f"[HOT-SWAP] Loading code from {file_path}")
        log(f"{'='*70}")

        with open(file_path, 'r') as f:
            new_code = f.read()

        log("[HOT-SWAP] Executing new code...")

        new_namespace = {
            'os': os,
            'types': types,
            'Path': Path,
            'dataclass': dataclass,
            'Community': Community,
            'CommunitySettings': CommunitySettings,
            'lazy_wrapper': lazy_wrapper,
            'DataClassPayload': DataClassPayload,
            'Peer': Peer,
            'MyMessage': MyMessage,
        }
        exec(new_code, new_namespace)

        new_community_class = new_namespace.get('MyCommunity')
        if not new_community_class:
            log("[HOT-SWAP] ERROR: No MyCommunity class found!")
            return

        log("[HOT-SWAP] Extracting on_message method...")
        new_on_message_func = new_community_class.on_message

        if hasattr(new_on_message_func, '__wrapped__'):
            log("[HOT-SWAP] Found wrapped method, extracting original function...")
            raw_func = new_on_message_func.__wrapped__
        else:
            raw_func = new_on_message_func

        log("[HOT-SWAP] Re-wrapping method with lazy_wrapper...")
        rewrapped_func = lazy_wrapper(MyMessage)(raw_func)
        bound_method = types.MethodType(rewrapped_func, self)

        self.on_message = bound_method
        self.decode_map[1] = bound_method

        log(f"{'='*70}")
        log(f">>> HOT-SWAP COMPLETE! Now using Community2 code <<<")
        log(f"{'='*70}")


async def start_communities() -> None:
    # Clear log file at startup
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    instances = []
    for i in [1, 2]:
        builder = ConfigBuilder().clear_keys().clear_overlays()
        builder.add_key("my peer", "medium", f"ec{i}.pem")
        builder.add_overlay("MyCommunity", "my peer",
                            [WalkerDefinition(Strategy.RandomWalk,
                                              10, {"timeout": 3.0})],
                            default_bootstrap_defs, {}, [("started",)])
        ipv8_instance = IPv8(builder.finalize(),
                             extra_communities={"MyCommunity": MyCommunity})
        await ipv8_instance.start()
        instances.append(ipv8_instance)

    # Wait for peers to discover each other
    log("Waiting for peer discovery...")
    await sleep(PEER_DISCOVERY_WAIT)

    # Get the communities
    community1 = instances[0].get_overlay(MyCommunity)

    # Check if they found each other
    peers1 = community1.get_peers()
    log(f"Community 1 has {len(peers1)} peers")
    log(f"System running. Watching for clock to reach 1000...")

    await run_forever()


run(start_communities())
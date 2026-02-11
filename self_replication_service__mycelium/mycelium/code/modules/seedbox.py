"""
BitTorrent seeding operations.

"""

import glob
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import libtorrent as lt

from config import Config
from utils import setup_logger


@dataclass
class ContentInfo:
    """Metadata for a seeded content file."""
    file_path: Path
    magnet_link: str
    url: Optional[str] = None
    license: Optional[str] = None

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class SeedboxError(Exception):
    pass


class Seedbox:
    """BitTorrent seeding operations for content distribution."""

    def __init__(
        self,
        content_dir: Path,
        tracker_url: str,
        port_min: int = 6881,
        port_max: int = 6891
    ):

        self.content_dir = Path(content_dir)
        self.tracker_url = tracker_url
        self.port_min = port_min
        self.port_max = port_max
        self.session = None
        self.handles: List[Tuple[lt.torrent_handle, str]] = []
        self.content_registry: Dict[str, ContentInfo] = {}  # infohash -> ContentInfo

    def _create_torrent(self, file_path: Path) -> Path:
        """
        Create torrent file from filepath

        Args:
            file_path: Path to-be-torrent file

        Returns:
            Path to .torrent file
        """
        torrent_file = Path(str(file_path) + ".torrent")

        if torrent_file.exists():
            logger.debug(f"Torrent already exists: {torrent_file.name}")
            return torrent_file

        logger.info(f"Creating torrent for: {file_path.name}")

        fs = lt.file_storage()
        lt.add_files(fs, str(file_path))

        t = lt.create_torrent(fs)
        t.add_tracker(self.tracker_url)
        t.set_creator("Mycelium Autonomous Seedbox")

        lt.set_piece_hashes(t, str(file_path.parent))
        torrent = t.generate()

        with open(torrent_file, "wb") as f:
            f.write(lt.bencode(torrent))

        logger.info(f"Torrent created: {torrent_file.name}")
        return torrent_file

    def _initialize_session(self) -> None:
        """Initialize libtorrent session"""
        self.session = lt.session()
        self.session.listen_on(self.port_min, self.port_max)

        settings = self.session.get_settings()
        settings['listen_interfaces'] = f'0.0.0.0:{self.port_min}'
        self.session.apply_settings(settings)

        logger.info(f"Session initialized on ports {self.port_min}-{self.port_max}")

    def _load_content_files(self) -> List[Path]:
        """
        Load content files from directory (excluding metadata files).

        Returns:
            List of file paths to seed
        """
        if not self.content_dir.exists():
            raise SeedboxError(f"Content directory not found: {self.content_dir}")

        files = glob.glob(str(self.content_dir / "*"))
        # Filter out .torrent and .info.json metadata files
        files = [
            Path(f) for f in files
            if not f.endswith('.torrent') and not f.endswith('.info.json')
        ]

        if not files:
            raise SeedboxError(f"No files found in: {self.content_dir}")

        logger.info(f"Found {len(files)} files to seed")
        return files

    def _load_metadata(self, file_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """
        Load metadata from .info.json file created by yt-dlp.

        Args:
            file_path: Path to the content file

        Returns:
            Tuple of (url, license) or (None, None) if not found
        """
        # Try different possible metadata file locations
        # yt-dlp creates: video_title.info.json for video_title.flac
        base_name = file_path.stem  # filename without extension
        info_file = file_path.parent / f"{base_name}.info.json"

        if not info_file.exists():
            # Try with full name (some formats keep extension in info filename)
            info_file = Path(str(file_path) + ".info.json")

        if not info_file.exists():
            logger.debug(f"No metadata file found for: {file_path.name}")
            return None, None

        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            url = metadata.get('webpage_url') or metadata.get('original_url')
            license_info = metadata.get('license', 'Creative Commons')

            logger.debug(f"Loaded metadata for {file_path.name}: url={url}")
            return url, license_info

        except Exception as e:
            logger.warning(f"Failed to load metadata for {file_path.name}: {e}")
            return None, None

    def _get_magnet_link(self, torrent_file: Path) -> str:
        """
        Generate magnet link from torrent file.

        Args:
            torrent_file: Path to .torrent file

        Returns:
            Magnet URI string
        """
        info = lt.torrent_info(str(torrent_file))
        return lt.make_magnet_uri(info)

    def _add_torrents(self, files: List[Path]) -> None:
        """
        Create and add torrents to session, populating content registry.

        Args:
            files: List of files to create torrents for
        """
        for file_path in files:
            try:
                torrent_file = self._create_torrent(file_path)
                info = lt.torrent_info(str(torrent_file))
                handle = self.session.add_torrent({
                    'ti': info,
                    'save_path': str(file_path.parent)
                })
                self.handles.append((handle, file_path.name))

                # Generate magnet link and load metadata
                magnet_link = self._get_magnet_link(torrent_file)
                url, license_info = self._load_metadata(file_path)
                infohash = str(info.info_hash())

                # Register content for IPV8 broadcast
                self.content_registry[infohash] = ContentInfo(
                    file_path=file_path,
                    magnet_link=magnet_link,
                    url=url,
                    license=license_info
                )

                logger.info(f"Added to session: {file_path.name} (infohash: {infohash[:16]}...)")
            except Exception as e:
                logger.error(f"Failed to add {file_path.name}: {e}")

    def get_content_for_broadcast(self) -> List[ContentInfo]:
        """
        Get all content info for IPV8 broadcast.

        Returns:
            List of ContentInfo objects with magnet links and metadata
        """
        return list(self.content_registry.values())

    def get_content_by_infohash(self, infohash: str) -> Optional[ContentInfo]:
        """
        Get content info by infohash.

        Args:
            infohash: The torrent infohash

        Returns:
            ContentInfo if found, None otherwise
        """
        return self.content_registry.get(infohash)

    def get_status(self) -> dict:
        """
        Get current seeding status

        Returns:
            Dictionary with status information
        """
        if not self.handles:
            return {"active": False, "torrents": 0, "peers": 0, "uploaded": 0}

        total_upload = 0
        total_peers = 0

        for handle, _ in self.handles:
            status = handle.status()
            total_upload += status.total_upload
            total_peers += status.num_peers

        return {
            "active": True,
            "torrents": len(self.handles),
            "peers": total_peers,
            "uploaded": total_upload
        }

    def initialize(self) -> None:
        """
        Initialize the seedbox session and load torrents.

        Call this before starting the seeding loop or announcer.
        Populates the content registry for IPV8 broadcasting.

        Raises:
            SeedboxError: If initialization fails
        """
        logger.info("Initializing seedbox")
        logger.info(f"Content directory: {self.content_dir}")
        logger.info(f"Tracker: {self.tracker_url}")

        self._initialize_session()
        files = self._load_content_files()
        self._add_torrents(files)

        if not self.handles:
            raise SeedboxError("No torrents loaded")

        logger.info(f"Seedbox initialized with {len(self.handles)} torrents")
        logger.info(f"Content registry has {len(self.content_registry)} entries")

    def run_status_loop(self, status_interval: int = 60) -> None:
        """
        Run the seeding status loop (blocking).

        Args:
            status_interval: Seconds between status updates
        """
        logger.info(f"Seeding {len(self.handles)} torrents")

        try:
            while True:
                status = self.get_status()
                logger.info(
                    f"Seeding: {status['torrents']} torrents, "
                    f"{status['peers']} peers, "
                    f"{status['uploaded'] / 1024 / 1024:.1f} MB uploaded"
                )
                time.sleep(status_interval)
        except KeyboardInterrupt:
            logger.info("Seedbox interrupted")
        finally:
            if self.session:
                logger.info("Stopping seedbox")

    def seed_content(self, status_interval: int = 5) -> None:
        """
        Initialize and run the main seeding loop.

        Args:
            status_interval: Seconds between status updates

        Raises:
            SeedboxError: If initialization fails
        """
        try:
            self.initialize()
            self.run_status_loop(status_interval)
        except SeedboxError:
            raise
        except Exception as e:
            logger.error(f"Seedbox error: {e}", exc_info=True)
            raise SeedboxError(f"Seeding failed: {e}")

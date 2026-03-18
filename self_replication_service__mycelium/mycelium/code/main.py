"""
Autonomous orchestrator main entry point.

Manages the event loop for code synchronization and seedbox operations.
"""

import asyncio
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modules.event_logger as event_logger
import modules.node_monitor as node_monitor
import modules.peer_registry as peer_registry
import modules.state as state_module
import modules.wallet as wallet_module
from config import Config
from modules import CodeSync, CodeSyncError, Seedbox, SeedboxError, LiberationAnnouncer, ContentDownloader, ContentDownloaderError
from utils import setup_logger

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


def _get_version() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(Config.BASE_DIR), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


class Orchestrator:
    """Main orchestrator for autonomous server operations."""

    def __init__(self):
        self.running = False
        self.code_sync = CodeSync(
            repo_path=Config.BASE_DIR,
            branch=Config.REPO_BRANCH
        )
        self.seedbox = Seedbox(
            content_dir=Config.CONTENT_DIR,
            tracker_url=Config.TORRENT_TRACKER,
            port_min=Config.SEEDBOX_PORT_MIN,
            port_max=Config.SEEDBOX_PORT_MAX
        )
        self.announcer = LiberationAnnouncer(self.seedbox)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Configure handlers for shutdown."""
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating shutdown")
        self.running = False

    async def check_for_updates(self) -> None:
        """Periodic task to check for code updates."""
        while self.running:
            try:
                if self.code_sync.has_updates():
                    logger.info("Updates detected on remote repository")
                    old_version = _get_version()
                    self.code_sync.pull_updates()
                    new_version = _get_version()
                    event_logger.get().log_event("restart", {
                        "old_version": old_version,
                        "new_version": new_version,
                    })
                    logger.info("Updates pulled successfully, restarting")
                    os._exit(Config.EXIT_RESTART)
            except CodeSyncError as e:
                logger.error(f"Code sync error: {e}")

            await asyncio.sleep(Config.UPDATE_CHECK_INTERVAL)

    async def heartbeat(self) -> None:
        """Periodic heartbeat logging."""
        while self.running:
            registry = peer_registry.get_registry()
            live_peers = registry.get_peer_count() if registry else 0
            logger.info("Orchestrator Running | live fleet peers: %d", live_peers)
            await asyncio.sleep(Config.HEARTBEAT_INTERVAL)

    async def download_content_if_needed(self) -> None:
        """Download content via yt-dlp if content directory is empty."""
        # Check if content already exists (ignore .info.json metadata files)
        content_files = [
            f for f in Config.CONTENT_DIR.iterdir()
            if f.is_file() and not f.name.endswith(".info.json")
        ] if Config.CONTENT_DIR.exists() else []

        if content_files:
            logger.info(f"Content directory already has {len(content_files)} files, skipping download")
            return

        if not Config.VIDEO_IDS_FILE.exists():
            logger.warning(f"Video IDs file not found at {Config.VIDEO_IDS_FILE}, skipping content download")
            return

        logger.info(f"Starting content download from {Config.VIDEO_IDS_FILE}")
        try:
            downloader = ContentDownloader(
                video_ids_file=Config.VIDEO_IDS_FILE,
                content_dir=Config.CONTENT_DIR,
                disk_threshold=Config.DISK_THRESHOLD,
                cookies_file=Config.COOKIES_FILE,
            )
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(self.executor, downloader.download_until_threshold)
            logger.info(f"Content download finished: {count} files downloaded")
        except ContentDownloaderError as e:
            logger.error(f"Content download failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected content download error: {e}", exc_info=True)

    async def initialize_seedbox(self) -> bool:
        """Initialize seedbox in executor thread."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor,
                self.seedbox.initialize
            )
            logger.info("Seedbox initialized successfully")
            return True
        except SeedboxError as e:
            logger.error(f"Seedbox initialization failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected seedbox init error: {e}", exc_info=True)
            return False

    async def run_seedbox_loop(self) -> None:
        """Run seedbox status loop in executor thread."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor,
                self.seedbox.run_status_loop,
                Config.SEEDBOX_STATUS_INTERVAL
            )
        except Exception as e:
            logger.error(f"Seedbox loop error: {e}", exc_info=True)

    async def run_announcer(self) -> None:
        """Run the IPV8 liberation announcer."""
        try:
            await self.announcer.start()
            await self.announcer.announce_loop(interval=Config.ANNOUNCE_INTERVAL)
        except Exception as e:
            logger.error(f"Announcer error: {e}", exc_info=True)
        finally:
            await self.announcer.stop()

    async def monitor_loop(self) -> None:
        """Periodically refresh node financial/operational state."""
        monitor = node_monitor.get_monitor()
        if not monitor:
            return
        while self.running:
            await asyncio.to_thread(monitor.refresh)
            await asyncio.sleep(node_monitor.NodeMonitor.REFRESH_INTERVAL)

    async def run_seedbox_info_announcer(self) -> None:
        """Run the seedbox info broadcast loop (waits for community init)."""
        logger.info("[SEEDBOX-INFO] Waiting for community to initialize...")
        # Wait until the announcer has initialized the community
        wait_count = 0
        while self.running and self.announcer.community is None:
            wait_count += 1
            if wait_count % 10 == 0:
                logger.info("[SEEDBOX-INFO] Still waiting for community... (%ds)", wait_count)
            await asyncio.sleep(1)

        if not self.running:
            logger.info("[SEEDBOX-INFO] Orchestrator stopped before community init")
            return

        logger.info("[SEEDBOX-INFO] Community ready, starting seedbox info loop")
        try:
            await self.announcer.seedbox_info_loop(interval=Config.WHOAMI_BROADCAST_INTERVAL)
        except Exception as e:
            logger.error(f"Seedbox info announcer error: {e}", exc_info=True)

    async def run(self) -> None:
        """Main orchestrator loop."""
        self.running = True
        logger.info("Orchestrator starting")
        logger.info(f"Repository: {Config.REPO_URL}")
        logger.info(f"Branch: {Config.REPO_BRANCH}")
        logger.info(f"Update check interval: {Config.UPDATE_CHECK_INTERVAL}s")
        logger.info(f"Content directory: {Config.CONTENT_DIR}")

        # Download content if needed (one-time, before seedbox)
        await self.download_content_if_needed()

        # Initialize seedbox first (blocking) so content is available for announcer
        if not await self.initialize_seedbox():
            logger.error("Cannot start without seedbox, exiting")
            return

        tasks = [
            asyncio.create_task(self.check_for_updates()),
            asyncio.create_task(self.heartbeat()),
            asyncio.create_task(self.run_seedbox_loop()),
            asyncio.create_task(self.run_announcer()),
            asyncio.create_task(self.run_seedbox_info_announcer()),
            asyncio.create_task(self.monitor_loop()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled, shutting down")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.executor.shutdown(wait=True)

        logger.info("Orchestrator stopped")


def main() -> int:
    """
    Application entry point.

    Returns:
        Exit code
    """
    try:
        Config.validate()

        # Persistent state — must be available before wallet or decision loop
        ps = state_module.init(Config.STATE_DB_FILE)
        if ps.get_caution_trait() == 0.5 and ps.get("caution_trait") is None:
            ps.set_caution_trait(Config.INITIAL_CAUTION_TRAIT)
            logger.info("Initialized caution trait to %.2f", Config.INITIAL_CAUTION_TRAIT)
        if ps.is_spawn_in_progress():
            logger.warning("Detected interrupted spawn from previous run — flag kept for decision loop")
        if ps.is_failsafe_in_progress():
            logger.warning("Detected interrupted failsafe from previous run — flag kept for decision loop")

        wallet_module.initialize_wallet()
        w = wallet_module.get_wallet()
        node_monitor.init(Config.SPORESTACK_TOKEN_FILE)
        peer_registry.init(ttl_seconds=Config.PEER_REGISTRY_TTL)
        event_logger.init(Config.LOG_ENDPOINT, Config.LOG_SECRET, Config.FRIENDLY_NAME)
        event_logger.get().log_event("birth", {
            "parent": Config.PARENT_NAME,
            "btc_address": w.get_receiving_address() if w else "",
            "starting_balance_sat": w.get_balance_satoshis() if w else 0,
            "version": _get_version(),
        })
        orchestrator = Orchestrator()
        asyncio.run(orchestrator.run())
        return Config.EXIT_SUCCESS
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return Config.EXIT_SUCCESS
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return Config.EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())

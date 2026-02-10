"""
Autonomous orchestrator main entry point.

Manages the event loop for code synchronization and seedbox operations.
"""

import asyncio
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import Config
from modules import CodeSync, CodeSyncError, Seedbox, SeedboxError, LiberationAnnouncer
from utils import setup_logger

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


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
                    self.code_sync.pull_updates()
                    logger.info("Updates pulled successfully, restarting")
                    os._exit(Config.EXIT_RESTART)
            except CodeSyncError as e:
                logger.error(f"Code sync error: {e}")

            await asyncio.sleep(Config.UPDATE_CHECK_INTERVAL)

    async def heartbeat(self) -> None:
        """Periodic heartbeat logging."""
        while self.running:
            logger.info("Orchestrator Running")
            await asyncio.sleep(Config.HEARTBEAT_INTERVAL)

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
            await self.announcer.announce_loop(interval=30)
        except Exception as e:
            logger.error(f"Announcer error: {e}", exc_info=True)
        finally:
            await self.announcer.stop()

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
            await self.announcer.seedbox_info_loop(interval=60)
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

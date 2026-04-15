from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

from healthchecker.db import purge_stale_entries
from healthchecker.liberation_service import LiberationService
from healthchecker.sampler import HealthChecker, now_unix

_STALE_CONTENT_THRESHOLD_SECONDS = 7200  # 2 hours without re-announcement → stale
_PURGE_INTERVAL_CYCLES = 1440            # purge every 1440 × 30s = 12 hours
_DHT_SAMPLES_KEEP = 30                   # max samples kept per infohash


class TorrentHealthThread(QThread):
    dataChanged = Signal()
    startedOk = Signal()
    error = Signal(str)

    def __init__(self, key_file: str, parent=None):
        super().__init__(parent)
        self._key_file = key_file
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._service: Optional[LiberationService] = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        self._stop_event.clear()
        self._service = LiberationService(key_file=self._key_file)

        # Start health checker in a daemon thread (blocking DHT ops, no asyncio needed)
        checker_thread = threading.Thread(target=self._run_health_checker, daemon=True)
        checker_thread.start()

        # Run LiberationService (IPv8) on an asyncio loop
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _start() -> None:
            try:
                await self._service.start()

                # Wrap community callbacks to also emit dataChanged
                orig_content = self._service.on_content_received
                orig_seedbox = self._service.on_seedbox_info_received

                def wrapped_content(peer, payload):
                    orig_content(peer, payload)
                    self.dataChanged.emit()

                def wrapped_seedbox(peer, payload):
                    orig_seedbox(peer, payload)
                    self.dataChanged.emit()

                if self._service.community:
                    self._service.community.set_content_received_callback(wrapped_content)
                    self._service.community.set_seedbox_info_callback(wrapped_seedbox)

                self.startedOk.emit()
            except Exception as e:
                self.error.emit(repr(e))

        self._loop.create_task(_start())

        try:
            self._loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop=self._loop)
                for t in pending:
                    t.cancel()
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop is None:
            return

        async def _shutdown() -> None:
            try:
                if self._service is not None:
                    await self._service.stop()
            finally:
                self._loop.stop()

        asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)

    def _run_health_checker(self) -> None:
        try:
            checker = HealthChecker()
            checker.initialize()  # bootstraps DHT (~10s)
        except Exception as e:
            self.error.emit(f"HealthChecker init failed: {e}")
            return

        cycle = 0
        while not self._stop_event.is_set():
            try:
                checker.run_once()
                self.dataChanged.emit()
            except Exception as e:
                print(f"HealthChecker error: {e}")

            cycle += 1
            if cycle % _PURGE_INTERVAL_CYCLES == 0:
                cutoff = now_unix() - _STALE_CONTENT_THRESHOLD_SECONDS
                removed = purge_stale_entries(cutoff, keep_samples=_DHT_SAMPLES_KEEP)
                if removed:
                    print(f"[Purge] Removed {removed} stale entries")
                    self.dataChanged.emit()

            # Sleep 30s but wake immediately if stop() is called
            self._stop_event.wait(30)

    def get_torrent_data(self) -> list[dict]:
        from healthchecker.db import get_all_torrents_with_health
        return get_all_torrents_with_health()

    def get_fleet_data(self) -> dict:
        if self._service is None:
            return {}
        return dict(self._service.seedbox_fleet)

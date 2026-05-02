from __future__ import annotations

import atexit
import json
import logging.config
import pathlib
import sys
from logging.handlers import QueueHandler
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent / "torrent_health_and_investment"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from config import DATA_PATH
from democracy.democracy_service import DemocracyService
from democracy.event_publisher import DemocracyEventPublisher
from democracy.models.person import Person
from democracy.network.ipv8_thread import IPv8Thread
from democracy.storage.repository_factory import DemocracyRepositoryFactory
from democracy.storage.sqlite_repository_factory import (
    SQLiteDemocracyRepositoryFactory,
)
from healthchecker.db import init_db
from healthchecker.health_thread import TorrentHealthThread
from ui.app import Application
from ui.common.fonts import load_application_fonts


def setup_logging() -> None:
    config_file = pathlib.Path(__file__).parent / "logging_config.json"

    with open(config_file, "r", encoding="utf-8") as f:
        logging_config = json.load(f)

    _ensure_log_directories_exist(logging_config, base_dir=config_file.parent)

    logging.config.dictConfig(logging_config)

    queue_listeners = []

    for handler_name in logging_config.get("handlers", {}):
        handler = logging.getHandlerByName(handler_name)

        if isinstance(handler, QueueHandler):
            listener = getattr(handler, "listener", None)

            if listener is not None:
                listener.start()
                queue_listeners.append(listener)

    if queue_listeners:
        atexit.register(_stop_queue_listeners, queue_listeners)


def _ensure_log_directories_exist(logging_config: dict, base_dir: pathlib.Path) -> None:
    """
    Create parent directories for all file-based logging handlers.

    Relative log file paths are resolved relative to the logging config file. The log file
    itself does not need to be created manually; the file handler creates it when logging
    starts.

    :param logging_config: The logging configuration dictionary.
    :param base_dir: The directory relative paths should be resolved against.
    :returns: None.
    """
    handlers = logging_config.get("handlers", {})

    for handler_config in handlers.values():
        filename = handler_config.get("filename")

        if filename is None:
            continue

        log_file = pathlib.Path(filename)

        if not log_file.is_absolute():
            log_file = base_dir / log_file
            handler_config["filename"] = str(log_file)

        log_file.parent.mkdir(parents=True, exist_ok=True)


def _stop_queue_listeners(queue_listeners: list) -> None:
    for listener in queue_listeners:
        listener.stop()


# -----------------------------
# App entrypoint
# -----------------------------
def main() -> None:
    # --- Logging ---
    setup_logging()

    # --- Session user ---
    user = Person()  # Person generates a random ID by default

    # --- Persistence ---
    base_path = Path(DATA_PATH) / str(user.id)
    database_path = base_path / "democracy.sqlite"

    repository_factory: DemocracyRepositoryFactory = SQLiteDemocracyRepositoryFactory(
        database_path
    )
    ui_repository = repository_factory.create_app_repository()

    # --- UI creation (main thread) ---
    app = QApplication(sys.argv)
    load_application_fonts()

    # --- Torrent health ---
    init_db()
    KEY_FILE = str(
        Path(__file__).parent / "torrent_health_and_investment" / "liberation_key.pem"
    )
    health_thread = TorrentHealthThread(key_file=KEY_FILE)
    health_thread.error.connect(lambda msg: print("Health error:", msg))
    health_thread.startedOk.connect(lambda: print("Health thread started"))
    health_thread.start()

    publisher = DemocracyEventPublisher()

    democracy_service = DemocracyService(
        ui_repository,
        publisher,
    )

    window = Application(
        user,
        democracy_service,
        health_thread,
    )

    # Start IPv8 in QThread
    worker = IPv8Thread(user.id, repository_factory)
    publisher.attach_worker(worker)
    worker.dataChanged.connect(
        window.schedule_refresh, type=Qt.ConnectionType.QueuedConnection
    )
    worker.error.connect(
        lambda msg: print("IPv8 error:", msg), type=Qt.ConnectionType.QueuedConnection
    )
    worker.startedOk.connect(
        lambda: print("IPv8 started"), type=Qt.ConnectionType.QueuedConnection
    )
    worker.start()

    # --- Run UI ---
    try:
        window.show()
        sys.exit(app.exec())
    finally:
        # Stop the background loop when the application exits
        health_thread.stop()
        health_thread.wait(1000)
        if worker is not None:
            worker.stop()
            worker.wait(1000)
        ui_repository.close()


if __name__ == "__main__":
    main()

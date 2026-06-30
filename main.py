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

from bitcoin.rpc_client import BitcoinRpcClient
from config import (
    COMMUNICATION_INTERVAL,
    DATA_PATH,
    FUNDING_MIN_CONFIRMATIONS,
    NETWORK_ID,
    REGTEST_RPC_CONFIG,
)
from democracy.democracy_service import DemocracyService
from democracy.event_publisher import DemocracyEventPublisher
from democracy.funding.service import FundingService
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
    base_dir = pathlib.Path(sys.executable).parent if getattr(sys, 'frozen', False) else pathlib.Path(__file__).parent
    config_file = base_dir / "logging_config.json"

    with open(config_file, "r", encoding="utf-8") as f:
        logging_config = json.load(f)

    _normalize_logging_config_for_python_version(logging_config)
    _ensure_log_directories_exist(logging_config, base_dir=base_dir)

    logging.config.dictConfig(logging_config)

    queue_listeners = []

    if sys.version_info < (3, 12):
        return

    for handler_name in logging_config.get("handlers", {}):
        handler = logging.getHandlerByName(handler_name)

        if isinstance(handler, QueueHandler):
            listener = getattr(handler, "listener", None)

            if listener is not None:
                listener.start()
                queue_listeners.append(listener)

    if queue_listeners:
        atexit.register(_stop_queue_listeners, queue_listeners)


def _normalize_logging_config_for_python_version(logging_config: dict) -> None:
    """
    Downgrade QueueHandler listener configuration for Python versions that do not support
    dictConfig-managed QueueHandler/QueueListener wiring.

    Python 3.12 added support for QueueHandler entries with "handlers" and
    "respect_handler_level" in dictConfig. On older versions, we replace references to
    those queue handlers with their target handlers and remove the queue handlers
    themselves.

    :param logging_config: The logging configuration dictionary.
    :returns: None.
    """
    if sys.version_info >= (3, 12):
        return

    handlers = logging_config.get("handlers", {})
    queue_targets: dict[str, list[str]] = {}

    for handler_name, handler_config in list(handlers.items()):
        if handler_config.get("class") != "logging.handlers.QueueHandler":
            continue

        target_handlers = handler_config.get("handlers", [])

        if isinstance(target_handlers, list):
            queue_targets[handler_name] = target_handlers

    if not queue_targets:
        return

    _replace_queue_handlers_in_logger_config(logging_config.get("root"), queue_targets)

    for logger_config in logging_config.get("loggers", {}).values():
        _replace_queue_handlers_in_logger_config(logger_config, queue_targets)

    for handler_name in queue_targets:
        handlers.pop(handler_name, None)


def _replace_queue_handlers_in_logger_config(
    logger_config: Optional[dict], queue_targets: dict[str, list[str]]
) -> None:
    if not logger_config:
        return

    configured_handlers = logger_config.get("handlers")

    if not isinstance(configured_handlers, list):
        return

    expanded_handlers = []

    for handler_name in configured_handlers:
        expanded_handlers.extend(queue_targets.get(handler_name, [handler_name]))

    logger_config["handlers"] = expanded_handlers


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
    base_path = Path(DATA_PATH) / "democracy" / str(user.id)
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
    bitcoin_rpc = BitcoinRpcClient.from_config(REGTEST_RPC_CONFIG)
    funding_service = FundingService(
        ui_repository,
        bitcoin_rpc,
        network_id=NETWORK_ID,
        min_confirmations=FUNDING_MIN_CONFIRMATIONS,
    )

    window = Application(
        user,
        democracy_service,
        funding_service,
        health_thread,
    )

    # Start IPv8 in QThread
    worker = IPv8Thread(
        user.id,
        repository_factory,
        data_path=DATA_PATH,
        communication_interval=COMMUNICATION_INTERVAL,
    )
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
        bitcoin_rpc.close()
        ui_repository.close()


if __name__ == "__main__":
    main()

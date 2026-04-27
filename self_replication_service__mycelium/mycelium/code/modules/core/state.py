"""
Persistent key-value state backed by SQLite.

Survives os._exit(42) restarts thanks to WAL mode with immediate commits.
"""

import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from config import Config
from utils import setup_logger

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


class NodePersistentState:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._conn.commit()

    # ── generic get / set / delete ──────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
        self._conn.commit()

    # ── caution trait ───────────────────────────────────────────

    def get_caution_trait(self) -> float:
        return float(self.get("caution_trait", 0.5))

    def set_caution_trait(self, value: float) -> None:
        self.set("caution_trait", value)

    # ── spawn guard ─────────────────────────────────────────────

    def is_spawn_in_progress(self) -> bool:
        return bool(self.get("spawn_in_progress", False))

    def get_spawn_id(self) -> str:
        return str(self.get("spawn_id", ""))

    def get_spawn_started_at(self) -> float:
        return float(self.get("spawn_started_at", 0) or 0)

    def mark_spawn_started(self, spawn_id: str) -> None:
        """Atomically set spawn_in_progress, spawn_id, and spawn_started_at.

        A crash between individual writes could leave spawn_in_progress=True with
        spawn_started_at=0, which would make _handle_shutdown's MAX_SPAWN_DURATION
        check fire instantly on the next signal and abandon a healthy spawn.
        """
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                ("spawn_in_progress", json.dumps(True)),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                ("spawn_id", json.dumps(spawn_id)),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                ("spawn_started_at", json.dumps(time.time())),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # Keys written by the spawn pipeline that must be cleared on completion so
    # they don't leak into the next spawn. Kept in one list so adding a new
    # intent key only requires updating this set and the writer.
    _SPAWN_KEYS_TO_CLEAR = (
        "spawn_id",
        "spawn_started_at",
        "spawn_identity",
        "spawn_vps_info",
        "spawn_child_wallet",
        "spawn_sporestack_token",
        "spawn_funding_intent",
        "spawn_funding_txid",
        "spawn_funding_attempts",
        "spawn_vps_intent",
        "spawn_transfer_intent",
        "spawn_transfer_txid",
    )

    def mark_spawn_completed(self, success: bool, child_btc_address: str = "") -> None:
        """Atomically clear spawn state in one SQL transaction.

        A crash between the old individual set/delete calls could leave the
        node with (e.g.) spawn_in_progress=False but spawn_identity still set,
        which would confuse the next spawn. Filesystem rmtree runs after the
        commit — it's not critical to atomicity and can fail benignly.
        """
        spawn_id = self.get_spawn_id()
        started_at = self.get("spawn_started_at", 0)
        history = self.get("spawn_history", []) if success else None
        if success:
            history.append({
                "spawn_id": spawn_id,
                "child_btc_address": child_btc_address,
                "started_at": started_at,
                "completed_at": time.time(),
                "success": True,
            })

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                ("spawn_in_progress", json.dumps(False)),
            )
            if success:
                self._conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    ("spawn_history", json.dumps(history)),
                )
            for key in self._SPAWN_KEYS_TO_CLEAR:
                self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        if success and spawn_id:
            spawn_dir = Config.DATA_DIR / "spawn" / spawn_id
            try:
                shutil.rmtree(spawn_dir)
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(
                    "Failed to remove spawn dir %s: %s. The child SSH private key may "
                    "still be on disk — operator should clean up manually.",
                    spawn_dir, e,
                )

    # ── failsafe guard ──────────────────────────────────────────

    def is_failsafe_in_progress(self) -> bool:
        return bool(self.get("failsafe_in_progress", False))

    def mark_failsafe_started(self) -> None:
        self.set("failsafe_in_progress", True)

    def mark_failsafe_completed(self) -> None:
        self.set("failsafe_in_progress", False)


# ── module-level singleton ──────────────────────────────────────

_instance: Optional[NodePersistentState] = None


def init(db_path: Path) -> NodePersistentState:
    global _instance
    _instance = NodePersistentState(db_path)
    logger.info("Persistent state initialized at %s", db_path)
    return _instance


def get() -> Optional[NodePersistentState]:
    return _instance

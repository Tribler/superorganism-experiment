from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from config import DATA_PATH
from models.issue import Issue
from models.person import Person
from models.vote import Vote
from network.ipv8_thread import IPv8Thread
from storage.json_store import JSONStore
from ui.app import Application

# -----------------------------
# App entrypoint
# -----------------------------
def main() -> None:
    # --- Session user ---
    user = Person()  # Person generates a random ID by default

    # --- Data stores ---
    issue_store = JSONStore[Issue](
        path=Path(DATA_PATH + str(user.id) + "/elections.json"),
        model_factory=Issue.from_dict,
        dictify=lambda e: e.to_dict()
    )
    vote_store = JSONStore[Vote](
        path=Path(DATA_PATH + str(user.id) + "/votes.json"),
        model_factory=Vote.from_dict,
        dictify=lambda v: v.to_dict()
    )

    # --- UI creation (main thread) ---
    app = QApplication(sys.argv)

    worker: Optional[IPv8Thread] = None

    def broadcast_new_issue(e: Issue) -> None:
        if worker is not None:
            worker.broadcastIssue.emit(e)

    def broadcast_new_vote(v: Vote) -> None:
        if worker is not None:
            worker.broadcastVote.emit(v)

    window = Application(user, issue_store, vote_store, broadcast_new_issue, broadcast_new_vote)

    # Start IPv8 in QThread
    worker = IPv8Thread(user.id, issue_store, vote_store)
    worker.dataChanged.connect(window.schedule_refresh, type=Qt.ConnectionType.QueuedConnection)
    worker.error.connect(lambda msg: print("IPv8 error:", msg), type=Qt.ConnectionType.QueuedConnection)
    worker.startedOk.connect(lambda: print("IPv8 started"), type=Qt.ConnectionType.QueuedConnection)
    worker.start()

    # --- Run UI ---
    try:
        window.show()
        sys.exit(app.exec())
    finally:
        # Stop the background loop when the application exits
        if worker is not None:
            worker.stop()
            worker.wait(1000)

if __name__ == "__main__":
    main()

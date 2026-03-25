from __future__ import annotations

import asyncio
import os
from collections import deque
from typing import Optional, Tuple, Union, Deque
from uuid import UUID

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from ipv8.configuration import ConfigBuilder, default_bootstrap_defs, Strategy, WalkerDefinition
from ipv8_service import IPv8

from communities.DemocracyCommunity import DemocracyCommunity
from models.issue import Issue
from models.vote import Vote
from storage.json_store import JSONStore


QueuedItem = Tuple[str, Union[Issue, Vote]]  # ("issue"|"vote", payload)


class IPv8Thread(QThread):
    """
    Runs IPv8 + an asyncio loop inside a QThread.
    Communication:
      - GUI -> Thread: broadcastIssue(Issue), broadcastVote(Vote)
      - Thread -> GUI: dataChanged(), startedOk(), error(str)
    """
    dataChanged = pyqtSignal()
    startedOk = pyqtSignal()
    error = pyqtSignal(str)

    # GUI -> worker signals
    broadcastIssue = pyqtSignal(object)     # Issue
    broadcastVote = pyqtSignal(object)      # Vote

    def __init__(
        self,
        user_id: UUID,
        issue_store: JSONStore[Issue],
        vote_store: JSONStore[Vote],
        parent=None,
    ):
        super().__init__(parent)
        self._user_id = user_id
        self._issue_store = issue_store
        self._vote_store = vote_store

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ipv8: Optional[IPv8] = None
        self._overlay: Optional[DemocracyCommunity] = None

        # Queue broadcasts that arrive before overlay is ready
        self._pending: Deque[QueuedItem] = deque()

        # Ensure GUI signals connect to thread slots via queued connection
        self.broadcastIssue.connect(self._on_broadcast_issue)
        self.broadcastVote.connect(self._on_broadcast_vote)

    # -----------------------
    # QThread entrypoint
    # -----------------------
    def run(self) -> None:
        """
        This runs in the new thread.
        Create and run an asyncio loop forever.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _start() -> None:
            try:
                self._overlay = await self._start_community()
                await self._flush_pending()  # flush queued messages right after startup
                self.startedOk.emit()
            except Exception as e:
                # Startup failed: drop pending
                self._pending.clear()
                self.error.emit(repr(e))

        self._loop.create_task(_start())

        try:
            self._loop.run_forever()
        finally:
            # Best-effort cleanup
            try:
                pending = asyncio.all_tasks(loop=self._loop)
                for t in pending:
                    t.cancel()
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    # -----------------------
    # Public shutdown
    # -----------------------
    def stop(self) -> None:
        """
        Called from GUI thread to stop IPv8 thread.
        """
        if self._loop is None:
            return

        async def _shutdown() -> None:
            try:
                if self._ipv8 is not None:
                    # ipv8_service supports stop() in most setups; if yours differs, adjust here
                    await self._ipv8.stop()
            finally:
                self._loop.stop()

        asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)

    # -----------------------
    # Community startup
    # -----------------------
    async def _start_community(self) -> DemocracyCommunity:
        builder = ConfigBuilder().clear_keys().clear_overlays()

        os.makedirs("keys", exist_ok=True)
        builder.add_key("my peer", "curve25519", f"keys/{str(self._user_id)}.pem")

        # Thread -> GUI callback: just emit signal; GUI will refresh (coalesced)
        def _data_changed_callback() -> None:
            self.dataChanged.emit()

        builder.add_overlay(
            overlay_class="DemocracyCommunity",
            key_alias="my peer",
            walkers=[WalkerDefinition(Strategy.RandomWalk, 10, {"timeout": 3.0})],
            bootstrappers=default_bootstrap_defs,
            initialize={
                "issue_store": self._issue_store,
                "vote_store": self._vote_store,
                "data_changed": _data_changed_callback,
            },
            on_start=[("on_start",)],
        )

        self._ipv8 = IPv8(builder.finalize(), extra_communities={"DemocracyCommunity": DemocracyCommunity})
        await self._ipv8.start()

        overlay = next(o for o in self._ipv8.overlays if isinstance(o, DemocracyCommunity))
        return overlay

    async def _flush_pending(self) -> None:
        """
        Flush queued broadcasts in order once overlay is ready.
        Runs in the worker thread's asyncio loop.
        """
        if self._overlay is None:
            return

        while self._pending:
            kind, payload = self._pending.popleft()

            if kind == "issue":
                self._overlay.on_create_issue(payload)  # type: ignore[arg-type]
            elif kind == "vote":
                self._overlay.on_vote(payload)  # type: ignore[arg-type]

        # After applying queued actions, signal the GUI to refresh once (coalesced on UI side)
        self.dataChanged.emit()

    # -----------------------
    # GUI -> worker slots
    # -----------------------
    @pyqtSlot(object)
    def _on_broadcast_issue(self, issue: Issue) -> None:
        """
        Runs in GUI thread when signal emitted, but executes in worker thread
        because this object lives in worker thread once started (queued conn).
        We schedule actual work on asyncio loop.
        """
        if self._loop is None:
            return

        async def _do() -> None:
            if self._overlay is None:
                self._pending.append(("issue", issue))
                return

            self._overlay.on_create_issue(issue)

        asyncio.run_coroutine_threadsafe(_do(), self._loop)

    @pyqtSlot(object)
    def _on_broadcast_vote(self, vote: Vote) -> None:
        if self._loop is None:
            return

        async def _do() -> None:
            if self._overlay is None:
                self._pending.append(("vote", vote))
                return

            self._overlay.on_vote(vote)

        asyncio.run_coroutine_threadsafe(_do(), self._loop)
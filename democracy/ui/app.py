from __future__ import annotations

import uuid
from typing import Callable, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMainWindow, QWidget, QGridLayout

from config import UI_REFRESH_DELAY
from models.election import Election
from models.person import Person
from models.vote import Vote
from storage.election_reposiory import ElectionRepository
from storage.json_store import JSONStore
from ui.widgets.create_election import CreateElectionWidget
from ui.widgets.election_details import ElectionDetailWidget
from ui.widgets.election_list import ElectionListWidget


class Application(QMainWindow):
    """
    Main application class for the Democracy UI.
    Manages the main window and coordinates between different widgets.
    1. Create Election Widget (left top)
    2. Election Detail Widget (right top)
    3. Election List Widget (bottom, spans full width)
    4. Session user management
    5. Event handling for creating elections, selecting elections, and voting.
    6. Data loading and refreshing.

    Args:
        election_store (JSONStore[Election]): Store for elections.
        vote_store (JSONStore[Vote]): Store for votes.
    """
    def __init__(
        self,
        user: Person,
        election_store: JSONStore[Election],
        vote_store: JSONStore[Vote],
        broadcast_new_election: Callable[[Election], None],
        broadcast_new_vote: Callable[[Vote], None],
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        self.user = user

        self.election_store = election_store
        self.vote_store = vote_store
        self.repo = ElectionRepository(election_store, vote_store)

        self.broadcast_new_election = broadcast_new_election
        self.broadcast_new_vote = broadcast_new_vote

        self.setWindowTitle("Democracy")

        # Central widget with grid layout
        central = QWidget()
        layout = QGridLayout(central)
        self.setCentralWidget(central)

        # Make columns expand and bottom row take remaining height
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)

        # Widgets
        self.create_widget = CreateElectionWidget()
        self.detail_widget = ElectionDetailWidget()
        self.list_widget = ElectionListWidget()

        # Layout: (0,0)=create, (0,1)=detail, (1,0..1)=list
        layout.addWidget(self.create_widget, 0, 0)
        layout.addWidget(self.detail_widget, 0, 1)
        layout.addWidget(self.list_widget, 1, 0, 1, 2)

        # Connect signals -> handlers
        self.create_widget.created.connect(self._on_create)
        self.list_widget.selected.connect(self._on_select)
        self.detail_widget.approved.connect(self._on_vote)

        # Coalesced refresh state
        self._refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # Initial load
        self.refresh()

    # -----------------------------
    # Refresh API
    # -----------------------------
    def refresh(self) -> None:
        """
        Immediate refresh (useful for local UI actions).
        """
        self.list_widget.load(self.repo.get_all())

        current_id = self.detail_widget.current_election_id
        if current_id:
            e = self.repo.get(current_id)
            if e:
                self.detail_widget.show(e)

    def schedule_refresh(self) -> None:
        """
        Coalesced refresh:
        - First call schedules a refresh in delay_ms.
        - Further calls before it fires do nothing.
        """
        if self._refresh_pending:
            return

        self._refresh_pending = True
        self._refresh_timer.start(UI_REFRESH_DELAY)

    def _do_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    # -----------------------------
    # Handlers
    # -----------------------------
    def _on_create(self, election: Election):
        """
        Handles creation of a new election. Sets the creator to the current user and adds it to the store.
        Refreshes the election list afterwards.

        :param election: Election to create.
        :return: None
        """
        election.creator_id = self.user.id
        self.election_store.add(election)

        self.refresh()

        self.broadcast_new_election(election)

    def _on_select(self, election_id: str):
        """
        Handles selection of an election from the list. Loads the election details into the detail frame.

        :param election_id: ID of the selected election.
        :return: None
        """
        election = self.repo.get(election_id)
        if election:
            self.detail_widget.show(election)

    def _on_vote(self, election_id: str):
        """
        Handles voting on an election. Checks if the user has already voted, and if not, records the vote.
        Refreshes the election list afterwards.

        :param election_id: ID of the selected election.
        :return: None
        """
        for v in self.vote_store.get_all():
            if v.voter_id == self.user.id and v.election_id == election_id:
                return # already voted

        vote = Vote(
            id=str(uuid.uuid4()),
            voter_id=self.user.id,
            election_id=election_id,
        )
        self.vote_store.add(vote)

        self.refresh()

        self.broadcast_new_vote(vote)
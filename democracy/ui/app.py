from __future__ import annotations

import sys
from typing import Callable

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout

from models.election import Election
from models.person import Person
from models.vote import Vote
from storage.election_reposiory import ElectionRepository
from storage.json_store import JSONStore
from ui.frames.create_election import CreateElectionFrame
from ui.frames.election_details import ElectionDetailFrame
from ui.frames.election_list import ElectionListFrame

class Application:
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
    ):
        self.user = user

        self.election_store = election_store
        self.vote_store = vote_store
        self.repo = ElectionRepository(election_store, vote_store)

        self.broadcast_new_election = broadcast_new_election
        self.broadcast_new_vote = broadcast_new_vote

        # Qt app + main window
        self.qt_app = QApplication([])
        self.window = QMainWindow()
        self.window.setWindowTitle("Democracy")

        # Central widget with grid layout
        central = QWidget()
        layout = QGridLayout(central)
        self.window.setCentralWidget(central)

        # Make columns expand and bottom row take remaining height
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)

        # Widgets
        self.create_frame = CreateElectionFrame(on_create=self._on_create)
        self.detail_frame = ElectionDetailFrame(on_vote=self._on_vote)
        self.list_frame = ElectionListFrame(on_select=self._on_select)

        # Layout: (0,0)=create, (0,1)=detail, (1,0..1)=list
        layout.addWidget(self.create_frame, 0, 0)
        layout.addWidget(self.detail_frame, 0, 1)
        layout.addWidget(self.list_frame, 1, 0, 1, 2)

        # Initial load
        self.list_frame.load(self.repo.get_all())

    def _on_create(self, election: Election):
        """
        Handles creation of a new election. Sets the creator to the current user and adds it to the store.
        Refreshes the election list afterwards.

        :param election: Election to create.
        :return: None
        """
        election.creator_id = self.user.id
        self.election_store.add(election)

        self.list_frame.load(self.repo.get_all())

        self.broadcast_new_election(election)

    def _on_select(self, election_id):
        """
        Handles selection of an election from the list. Loads the election details into the detail frame.

        :param election_id: ID of the selected election.
        :return: None
        """
        election = self.repo.get(election_id)
        if election:
            self.detail_frame.show(election)

    def _on_vote(self, vote):
        """
        Handles voting on an election. Checks if the user has already voted, and if not, records the vote.
        Refreshes the election list afterwards.

        :param vote: Vote to record.
        :return: None
        """
        for v in self.vote_store.get_all():
            if v.voter_id == self.user.id and v.election_id == vote.election_id:
                return # already voted

        vote.voter_id = self.user.id
        self.vote_store.add(vote)

        self._on_select(vote.election_id)
        self.list_frame.load(self.repo.get_all())

        self.broadcast_new_vote(vote)

    def run(self):
        """
        Starts the main application loop.

        :return: None
        """
        self.window.show()
        sys.exit(self.qt_app.exec())
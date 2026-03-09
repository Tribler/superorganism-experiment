from __future__ import annotations

import uuid
from typing import Callable, Optional

from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QGridLayout
from PyQt6.QtCore import Qt, pyqtSignal

from models.DTOs.issue_with_votes import IssueWithVotes
from models.vote import Vote


class IssueDetailWidget(QWidget):
    approved = pyqtSignal(str)

    """
    Displays a single issue's details.
    Calls on_vote(vote) when the Approve button is clicked.

    Args:
        on_vote: Callback function when a vote is cast.
        parent: Parent widget.
    """
    def __init__(self, on_vote: Optional[Callable[[Vote], None]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.on_vote = on_vote

        self.current_issue_id: Optional[str] = None

        layout = QGridLayout(self)

        layout.addWidget(QLabel("Issue ID:"), 0, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.issue_id_lbl = QLabel("")
        self.issue_id_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.issue_id_lbl, 0, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Creator:"), 1, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.creator_lbl = QLabel("")
        self.creator_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.creator_lbl, 1, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Created at:"), 2, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.created_at_lbl = QLabel("")
        self.created_at_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.created_at_lbl, 2, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Title:"), 3, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.title_lbl = QLabel("")
        self.title_lbl.setWordWrap(True)
        layout.addWidget(self.title_lbl, 3, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Description:"), 4, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.desc_lbl = QLabel("")
        self.desc_lbl.setWordWrap(True)
        layout.addWidget(self.desc_lbl, 4, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Threshold:"), 5, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.threshold_lbl = QLabel("")
        layout.addWidget(self.threshold_lbl, 5, 1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Votes:"), 6, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.votes_lbl = QLabel("")
        layout.addWidget(self.votes_lbl, 6, 1, alignment=Qt.AlignmentFlag.AlignTop)

        self.approve_btn = QPushButton("Approve")
        self.approve_btn.clicked.connect(self._vote)
        layout.addWidget(self.approve_btn, 6, 2)

        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 0)

        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        self.approve_btn.setEnabled(enabled)

    def show(self, i: IssueWithVotes):
        """
        Loads the issue details into the frame.

        :param i: IssueWithVotes to display.
        :return: None
        """
        self.current_issue_id = i.issue.id

        self.issue_id_lbl.setText(i.issue.id)
        self.creator_lbl.setText(str(i.issue.creator_id))
        self.created_at_lbl.setText(str(i.issue.created_at))
        self.title_lbl.setText(i.issue.title)
        self.desc_lbl.setText(i.issue.description or "")
        self.threshold_lbl.setText(str(i.issue.threshold))
        self.votes_lbl.setText(str(i.votes))

        self._set_enabled(True)

    def _vote(self):
        """
        Handles voting and calls the on_vote callback.

        :return: None
        """
        if self.current_issue_id:
            self.approved.emit(self.current_issue_id)

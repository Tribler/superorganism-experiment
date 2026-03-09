from __future__ import annotations

import uuid
from typing import Callable, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, \
    QLabel, QLineEdit, QComboBox

from config import UI_REFRESH_DELAY
from models.issue import Issue
from models.person import Person
from models.vote import Vote
from storage.issue_reposiory import IssueRepository
from storage.json_store import JSONStore
from ui.widgets.create_issue import CreateIssueWidget
from ui.widgets.create_issue_dialog import CreateIssueDialog
from ui.widgets.issue_details import IssueDetailWidget
from ui.widgets.issue_table import IssueTableWidget


class IssueDetailDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Issue Details")
        self.resize(700, 300)

        layout = QVBoxLayout(self)
        self.detail_widget = IssueDetailWidget()
        layout.addWidget(self.detail_widget)

    def show_issue(self, issue_with_votes) -> None:
        self.detail_widget.show(issue_with_votes)


class Application(QMainWindow):
    """
    Main application class for the Democracy UI.
    Manages the main window and coordinates between different widgets.
    1. Create Issue Widget (left top)
    2. Issue Detail Widget (right top)
    3. Issue List Widget (bottom, spans full width)
    4. Session user management
    5. Event handling for creating issues, selecting issues, and voting.
    6. Data loading and refreshing.

    Args:
        issue_store (JSONStore[Issue]): Store for issues.
        vote_store (JSONStore[Vote]): Store for votes.
    """
    def __init__(
        self,
        user: Person,
        issue_store: JSONStore[Issue],
        vote_store: JSONStore[Vote],
        broadcast_new_issue: Callable[[Issue], None],
        broadcast_new_vote: Callable[[Vote], None],
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        self.user = user

        self.issue_store = issue_store
        self.vote_store = vote_store
        self.repo = IssueRepository(issue_store, vote_store)

        self.broadcast_new_issue = broadcast_new_issue
        self.broadcast_new_vote = broadcast_new_vote

        self.setWindowTitle("Democracy")
        self.resize(1360, 820)

        # Coalesced refresh state
        self._refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        self.detail_dialog = IssueDetailDialog(self)
        self.detail_dialog.detail_widget.approved.connect(self._on_vote)

        root = QWidget()
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        content = self._build_content()

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)

        # Initial load
        self.refresh()

        self._apply_styles()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(260)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 90, 18, 18)
        layout.setSpacing(12)

        self.dashboard_btn = QPushButton("Dashboard")
        self.dashboard_btn.setObjectName("navActive")

        self.my_proposals_btn = QPushButton("My Issues")
        self.voting_history_btn = QPushButton("Voting History")
        self.settings_btn = QPushButton("Settings")

        for btn in [
            self.dashboard_btn,
            self.my_proposals_btn,
            self.voting_history_btn,
            self.settings_btn,
        ]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor if hasattr(__import__("PyQt6.QtCore").QtCore, "Qt") else btn.cursor())

        layout.addWidget(self.dashboard_btn)
        layout.addWidget(self.my_proposals_btn)
        layout.addWidget(self.voting_history_btn)
        layout.addWidget(self.settings_btn)
        layout.addStretch()

        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        header = QHBoxLayout()
        self.title_label = QLabel("Community Governance Dashboard")
        self.title_label.setObjectName("pageTitle")

        self.create_btn = QPushButton("Create New Issue")
        self.create_btn.setObjectName("primaryButton")
        self.create_btn.clicked.connect(self._open_create_dialog)

        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.create_btn)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(14)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search")
        self.search_input.textChanged.connect(self._on_search_changed)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Open", "Passed", "Needs Votes"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)

        toolbar.addWidget(self.search_input, 1)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Filter by:"))
        toolbar.addWidget(self.filter_combo)

        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.issue_table = IssueTableWidget()
        self.issue_table.selected.connect(self._on_select)
        self.issue_table.activated.connect(self._open_detail_dialog)

        table_layout.addWidget(self.issue_table)

        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(table_card, 1)

        return content

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background: #0b1220;
            }

            #sidebar {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a2433,
                    stop:1 #111827
                );
                border-right: 1px solid rgba(255,255,255,0.08);
            }

            QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }

            #pageTitle {
                font-size: 28px;
                font-weight: 700;
                color: white;
            }

            QPushButton {
                background: transparent;
                color: #cbd5e1;
                border: none;
                border-radius: 12px;
                padding: 14px 16px;
                text-align: left;
                font-size: 15px;
            }

            QPushButton:hover {
                background: rgba(255,255,255,0.06);
            }

            QPushButton#navActive {
                background: rgba(255,255,255,0.10);
                color: white;
                font-weight: 600;
            }

            QPushButton#primaryButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3b82f6,
                    stop:1 #2563eb
                );
                color: white;
                font-weight: 600;
                padding: 14px 22px;
            }

            QPushButton#primaryButton:hover {
                background: #3b82f6;
            }

            QLineEdit, QComboBox {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 12px 14px;
                color: white;
                min-height: 22px;
            }

            #tableCard {
                background: rgba(255,255,255,0.02);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 16px;
            }
        """)

    # -----------------------------
    # Refresh API
    # -----------------------------
    def refresh(self) -> None:
        """
        Immediate refresh (useful for local UI actions).
        """
        self.issue_table.load(self.repo.get_all())

        current_id = self.detail_dialog.detail_widget.current_issue_id
        if current_id:
            e = self.repo.get(current_id)
            if e:
                self.detail_dialog.show_issue(e)

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

    def _open_create_dialog(self) -> None:
        dialog = CreateIssueDialog(self)
        dialog.created.connect(self._on_create)
        dialog.exec()

    def _on_search_changed(self, text: str) -> None:
        self.issue_table.set_search_text(text)

    def _on_filter_changed(self, value: str) -> None:
        self.issue_table.set_filter_mode(value)

    # -----------------------------
    # Handlers
    # -----------------------------
    def _on_create(self, issue: Issue):
        """
        Handles creation of a new issue. Sets the creator to the current user and adds it to the store.
        Refreshes the issue list afterwards.

        :param issue: Issue to create.
        :return: None
        """
        issue.creator_id = self.user.id
        self.issue_store.add(issue)

        self.refresh()

        self.broadcast_new_issue(issue)

    def _on_select(self, issue_id: str):
        """
        Handles selection of an issue from the list. Loads the issue details into the detail frame.

        :param issue_id: ID of the selected issue.
        :return: None
        """
        issue = self.repo.get(issue_id)
        if issue:
            self.detail_dialog.show_issue(issue)

    def _open_detail_dialog(self, issue_id: str) -> None:
        print("open dialog for:", issue_id)
        issue = self.repo.get(issue_id)
        print("repo returned:", issue)
        if issue:
            self.detail_dialog.show_issue(issue)
            self.detail_dialog.exec()

    def _on_vote(self, issue_id: str):
        """
        Handles voting on an issue. Checks if the user has already voted, and if not, records the vote.
        Refreshes the issue list afterwards.

        :param issue_id: ID of the selected issue.
        :return: None
        """
        for v in self.vote_store.get_all():
            if v.voter_id == self.user.id and v.issue_id == issue_id:
                return # already voted

        vote = Vote(
            id=str(uuid.uuid4()),
            voter_id=self.user.id,
            issue_id=issue_id,
        )
        self.vote_store.add(vote)

        self.refresh()

        self.broadcast_new_vote(vote)
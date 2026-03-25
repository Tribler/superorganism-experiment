from __future__ import annotations


from uuid import uuid4, UUID
from typing import Callable, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QPushButton,
    QLabel,
    QLineEdit,
    QComboBox,
    QStackedWidget
)

from config import UI_REFRESH_DELAY
from models.issue import Issue
from models.person import Person
from models.solution import Solution
from models.vote import Vote
from storage.issue_reposiory import IssueRepository
from storage.json_store import JSONStore
from ui.models.issue_draft import IssueDraft
from ui.widgets.create_issue_overlay import CreateIssueOverlay
from ui.widgets.issue_details import IssueDetailWidget
from ui.widgets.issue_table import IssueTableWidget


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

        root = QWidget()
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = self._build_sidebar()

        self.content_stack = QStackedWidget()

        self.dashboard_page = self._build_dashboard_page()
        self.issue_detail_page = IssueDetailWidget()

        self.issue_detail_page.back_clicked.connect(self._show_dashboard_page)
        self.issue_detail_page.approved.connect(self._on_vote)
        self.issue_detail_page.solution_voted.connect(self._on_solution_vote)
        self.issue_detail_page.solution_details_requested.connect(self._on_solution_details)

        self.content_stack.addWidget(self.dashboard_page)
        self.content_stack.addWidget(self.issue_detail_page)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.content_stack, 1)

        self.content_stack.setCurrentWidget(self.dashboard_page)

        self.create_issue_overlay = CreateIssueOverlay(root)
        self.create_issue_overlay.created.connect(self._on_create)
        self.create_issue_overlay.hide()

        # Initial load
        self.refresh()

        self._apply_styles()

    def _mock_solutions_for_issue(self, issue: Issue) -> list:
        return [
            Solution(
                id="sol-1",
                title="Improve validation and review flow",
                description="Introduce a clearer validation pipeline and a better review UI so voters can understand the issue and decide faster.",
                votes=42,
                status_text="Validated by core team",
                highlighted=True,
            ),
            Solution(
                id="sol-2",
                title="Split issue discussion from final voting",
                description="Allow issue discussion and solution voting to happen separately so users can support the issue without prematurely endorsing one implementation.",
                votes=17,
                status_text="Under technical review",
                highlighted=False,
            ),
        ]

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

    def _build_dashboard_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        header = QHBoxLayout()
        self.title_label = QLabel("Community Governance Dashboard")
        self.title_label.setObjectName("pageTitle")

        self.create_btn = QPushButton("Create New Issue")
        self.create_btn.setObjectName("primaryButton")
        self.create_btn.clicked.connect(self._open_create_overlay)

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
        self.issue_table.activated.connect(self._open_issue_details)

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

        current_id = self.issue_detail_page.current_issue_id
        if current_id:
            e = self.repo.get(current_id)
            if e:
                self.issue_detail_page.show_issue(
                    e,
                    self._mock_solutions_for_issue(e.issue)
                )

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

    def _open_create_overlay(self) -> None:
        self.create_issue_overlay.open_overlay()

    def _on_search_changed(self, text: str) -> None:
        self.issue_table.set_search_text(text)

    def _on_filter_changed(self, value: str) -> None:
        self.issue_table.set_filter_mode(value)

    # -----------------------------
    # Handlers
    # -----------------------------
    def _on_create(self, draft: IssueDraft):
        """
        Handles creation of a new issue. Sets the creator to the current user and adds it to the store.
        Refreshes the issue list afterwards.

        :param draft: Issue to create.
        :return: None
        """
        errors = draft.validate()
        if errors:
            return

        issue = Issue(
            title=draft.title,
            description=draft.description,
            creator_id=self.user.id,
        )

        self.issue_store.add(issue)
        self.refresh()
        self.broadcast_new_issue(issue)

    def _on_select(self, issue_id: UUID):
        """
        Handles selection of an issue from the list. Loads the issue details into the detail frame.

        :param issue_id: ID of the selected issue.
        :return: None
        """
        pass

    def _open_issue_details(self, issue_id: UUID) -> None:
        self._show_issue_detail_page(issue_id)

    def _on_vote(self, issue_id: UUID):
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
            voter_id=self.user.id,
            issue_id=issue_id,
        )
        self.vote_store.add(vote)

        self.refresh()

        self.broadcast_new_vote(vote)

    def _on_solution_vote(self, issue_id: UUID, solution_id: str) -> None:
        print(f"Vote on solution {solution_id} for issue {issue_id}")

    def _on_solution_details(self, issue_id: UUID, solution_id: str) -> None:
        print(f"Open details for solution {solution_id} of issue {issue_id}")

    def _show_dashboard_page(self) -> None:
        self.content_stack.setCurrentWidget(self.dashboard_page)

    def _show_issue_detail_page(self, issue_id: UUID) -> None:
        issue = self.repo.get(issue_id)
        if not issue:
            return

        self.issue_detail_page.show_issue(
            issue,
            self._mock_solutions_for_issue(issue.issue),
        )
        self.content_stack.setCurrentWidget(self.issue_detail_page)
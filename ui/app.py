from __future__ import annotations


from uuid import UUID
from typing import TYPE_CHECKING, Callable, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QStackedWidget
)

from config import UI_REFRESH_DELAY
from democracy.models.issue import Issue
from democracy.models.person import Person
from democracy.models.solution import Solution
from democracy.models.vote import Vote
from democracy.storage.issue_reposiory import IssueRepository
from democracy.storage.json_store import JSONStore
from ui.models.issue_draft import IssueDraft
from ui.widgets.create_issue_overlay import CreateIssueOverlay
from ui.widgets.fleet_widget import FleetWidget
from ui.widgets.issue_details import IssueDetailWidget
from ui.widgets.issue_overview import IssuesOverviewWidget
from ui.widgets.sidebar import SidebarWidget
from ui.widgets.torrents_widget import TorrentsWidget

if TYPE_CHECKING:
    from healthchecker.health_thread import TorrentHealthThread


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
        health_thread: TorrentHealthThread,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        self.user = user

        self.issue_store = issue_store
        self.vote_store = vote_store
        self.repo = IssueRepository(issue_store, vote_store)

        self.broadcast_new_issue = broadcast_new_issue
        self.broadcast_new_vote = broadcast_new_vote
        self._health_thread = health_thread

        self.setWindowTitle("Democracy")
        self.resize(1360, 820)

        # Coalesced refresh state
        self._refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = SidebarWidget()

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStackHost")

        self.issues_page = IssuesOverviewWidget()

        self.issues_page.create_clicked.connect(self._open_create_overlay)
        self.issues_page.search_changed.connect(self._on_search_changed)
        self.issues_page.filter_changed.connect(self._on_filter_changed)
        self.issues_page.issue_selected.connect(self._on_select)
        self.issues_page.issue_activated.connect(self._open_issue_details)

        self.issue_detail_page = IssueDetailWidget()

        self.issue_detail_page.back_clicked.connect(self._show_issues_page)
        self.issue_detail_page.approved.connect(self._on_vote)
        self.issue_detail_page.solution_voted.connect(self._on_solution_vote)
        self.issue_detail_page.solution_details_requested.connect(self._on_solution_details)

        self.torrents_page = TorrentsWidget()
        self.fleet_page = FleetWidget()

        self.content_stack.addWidget(self.torrents_page)
        self.content_stack.addWidget(self.fleet_page)
        self.content_stack.addWidget(self.issues_page)
        self.content_stack.addWidget(self.issue_detail_page)

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.content_stack, 1)

        self.content_stack.setCurrentWidget(self.issues_page)

        self.sidebar.torrents_clicked.connect(self._show_torrents_page)
        self.sidebar.fleet_clicked.connect(self._show_fleet_page)
        self.sidebar.issues_clicked.connect(self._show_issues_page)
        self.sidebar.my_issues_clicked.connect(lambda: print("My Issues clicked"))
        self.sidebar.voting_history_clicked.connect(lambda: print("Voting History clicked"))
        self.sidebar.settings_clicked.connect(lambda: print("Settings clicked"))
        self.sidebar.create_clicked.connect(self._open_create_overlay)

        health_thread.dataChanged.connect(
            self._on_health_data_changed, type=Qt.ConnectionType.QueuedConnection
        )

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

    def _apply_styles(self) -> None:
        with open("ui/styles/main.qss", "r") as f:
            self.setStyleSheet(f.read())

    # -----------------------------
    # Refresh API
    # -----------------------------
    def refresh(self) -> None:
        """
        Immediate refresh (useful for local UI actions).
        """
        self.issues_page.load(self.repo.get_all())

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
        self.issues_page.apply_search_filter(text)

    def _on_filter_changed(self, value: str) -> None:
        self.issues_page.apply_status_filter(value)

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

    def _set_active_nav(self, active_name: str) -> None:
        self.sidebar.set_active_by_name(active_name)

    def _show_issues_page(self) -> None:
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issues_page)

    def _show_issue_detail_page(self, issue_id: UUID) -> None:
        issue = self.repo.get(issue_id)
        if not issue:
            return

        self.issue_detail_page.show_issue(
            issue,
            self._mock_solutions_for_issue(issue.issue),
        )
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issue_detail_page)

    def _show_torrents_page(self) -> None:
        self._set_active_nav("torrents")
        self.content_stack.setCurrentWidget(self.torrents_page)

    def _show_fleet_page(self) -> None:
        self._set_active_nav("fleet")
        self.content_stack.setCurrentWidget(self.fleet_page)

    def _on_health_data_changed(self) -> None:
        self.torrents_page.load(self._health_thread.get_torrent_data())
        self.fleet_page.load(self._health_thread.get_fleet_data())
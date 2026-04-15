from __future__ import annotations


from uuid import UUID
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QStackedWidget
)

from config import UI_REFRESH_DELAY
from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.person import Person
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.storage.democracy_reposiory import DemocracyRepository
from democracy.storage.json_store import JSONStore
from ui.models.issue_draft import IssueDraft
from ui.models.solution_draft import SolutionDraft
from ui.widgets.create_issue_overlay import CreateIssueOverlay
from ui.widgets.create_solution_overlay import CreateSolutionOverlay
from ui.widgets.fleet_widget import FleetWidget
from ui.widgets.issue_details import IssueDetailWidget
from ui.widgets.issue_overview import IssuesOverviewWidget
from ui.widgets.ltr_community_widget import LTRCommunityWidget
from ui.widgets.sidebar import SidebarWidget
from ui.widgets.solution_details import SolutionDetailWidget
from ui.widgets.torrents_widget import TorrentsWidget

from crowdsourced_learn_to_rank.ltr_community_thread import LTRCommunityThread

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
        issue_vote_store (JSONStore[Vote]): Store for votes.
    """
    def __init__(
        self,
        user: Person,
        issue_store: JSONStore[Issue],
        issue_vote_store: JSONStore[IssueVote],
        solution_store: JSONStore[Solution],
        solution_vote_store: JSONStore[SolutionVote],
        broadcast_new_issue: Callable[[Issue], None],
        broadcast_new_issue_vote: Callable[[IssueVote], None],
        broadcast_new_solution: Callable[[Solution], None],
        broadcast_new_solution_vote: Callable[[SolutionVote], None],
        health_thread: TorrentHealthThread,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.user = user

        self.issue_store = issue_store
        self.issue_vote_store = issue_vote_store
        self.solution_store = solution_store
        self.solution_vote_store = solution_vote_store

        self.repo = DemocracyRepository(issue_store, issue_vote_store, solution_store, solution_vote_store)

        self.broadcast_new_issue = broadcast_new_issue
        self.broadcast_new_issue_vote = broadcast_new_issue_vote
        self.broadcast_new_solution = broadcast_new_solution
        self.broadcast_new_solution_vote = broadcast_new_solution_vote

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
        self.issue_detail_page.open_create_solution.connect(self._open_create_solution_overlay)

        self._solution_target_issue_id: Optional[UUID] = None

        self.solution_detail_page = SolutionDetailWidget()
        self.solution_detail_page.back_clicked.connect(self._show_issue_detail_page_for_current_issue)
        self.solution_detail_page.voted.connect(self._on_vote_solution_directly)
        self.solution_detail_page.code_verification_clicked.connect(self._on_code_verification_clicked)

        self.torrents_page = TorrentsWidget()
        self.fleet_page = FleetWidget()

        self.experiment_page = LTRCommunityWidget()
        self.experiment_page.run_requested.connect(self._on_experiment_run_requested)
        self._ltr_thread: Optional[LTRCommunityThread] = None

        self.content_stack.addWidget(self.torrents_page)
        self.content_stack.addWidget(self.fleet_page)
        self.content_stack.addWidget(self.issues_page)
        self.content_stack.addWidget(self.issue_detail_page)
        self.content_stack.addWidget(self.solution_detail_page)
        self.content_stack.addWidget(self.experiment_page)

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.content_stack, 1)

        self.content_stack.setCurrentWidget(self.issues_page)

        self.sidebar.torrents_clicked.connect(self._show_torrents_page)
        self.sidebar.fleet_clicked.connect(self._show_fleet_page)
        self.sidebar.issues_clicked.connect(self._show_issues_page)
        self.sidebar.my_issues_clicked.connect(lambda: print("My Issues clicked"))
        self.sidebar.voting_history_clicked.connect(lambda: print("Voting History clicked"))
        self.sidebar.experiment_clicked.connect(self._show_experiment_page)
        self.sidebar.settings_clicked.connect(lambda: print("Settings clicked"))
        self.sidebar.create_clicked.connect(self._open_create_overlay)

        health_thread.dataChanged.connect(
            self._on_health_data_changed, type=Qt.ConnectionType.QueuedConnection
        )

        # Populate torrent table immediately with all known peers (unchecked show "-")
        self.torrents_page.load(health_thread.get_torrent_data())

        self.create_issue_overlay = CreateIssueOverlay(root)
        self.create_issue_overlay.created.connect(self._on_create_issue)
        self.create_issue_overlay.hide()

        self.create_solution_overlay = CreateSolutionOverlay(root)
        self.create_solution_overlay.created.connect(self._on_create_solution)
        self.create_solution_overlay.hide()

        # Initial load
        self.refresh()

        self._apply_styles()

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
        self.issues_page.load(self.repo.get_all_issues_with_votes())

        current_id = self.issue_detail_page.current_issue_id
        if current_id:
            issue = self.repo.get_issue_with_votes(current_id)
            if issue:
                solutions = self.repo.get_solutions_for_issue_with_votes(current_id)
                self.issue_detail_page.show_issue(issue, solutions)

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
    def _on_create_issue(self, draft: IssueDraft):
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
        if self.repo.has_user_voted_for_issue(self.user.id, issue_id):
            return # already voted

        vote = IssueVote(
            voter_id=self.user.id,
            issue_id=issue_id,
        )
        self.issue_vote_store.add(vote)

        self.refresh()
        self.broadcast_new_issue_vote(vote)

    def _on_solution_vote(self, issue_id: UUID, solution_id: UUID) -> None:
        if self.repo.has_user_voted_for_solution(self.user.id, solution_id):
            return

        vote = SolutionVote(
            voter_id=self.user.id,
            solution_id=solution_id,
        )
        self.solution_vote_store.add(vote)

        self.refresh()
        self.broadcast_new_solution_vote(vote)

    def _on_solution_details(self, issue_id: UUID, solution_id: UUID) -> None:
        solution = self.repo.get_solution_with_votes(solution_id)
        if not solution:
            return

        self._current_parent_issue_id = issue_id
        self.solution_detail_page.show_solution(solution)
        self.content_stack.setCurrentWidget(self.solution_detail_page)

    def _set_active_nav(self, active_name: str) -> None:
        self.sidebar.set_active_by_name(active_name)

    def _show_issues_page(self) -> None:
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issues_page)

    def _show_issue_detail_page(self, issue_id: UUID) -> None:
        issue = self.repo.get_issue_with_votes(issue_id)
        if not issue:
            return

        solutions = self.repo.get_solutions_for_issue_with_votes(issue_id)

        self.issue_detail_page.show_issue(
            issue,
            solutions,
        )
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issue_detail_page)

    def _open_create_solution_overlay(self, issue_id: UUID) -> None:
        self._solution_target_issue_id = issue_id
        self.create_solution_overlay.open_overlay()

    def _on_create_solution(self, draft: SolutionDraft) -> None:
        if self._solution_target_issue_id is None:
            return

        errors = draft.validate()
        if errors:
            return

        solution = Solution(
            title=draft.title,
            description=draft.description,
            creator_id=self.user.id,
            issue_id=self._solution_target_issue_id,
        )

        self.solution_store.add(solution)
        self.refresh()
        self.broadcast_new_solution(solution)

    def _show_issue_detail_page_for_current_issue(self) -> None:
        current_id = self.issue_detail_page.current_issue_id
        if current_id is not None:
            self._show_issue_detail_page(current_id)

    def _on_vote_solution_directly(self, solution_id: UUID) -> None:
        current_issue_id = self.issue_detail_page.current_issue_id
        if current_issue_id is not None:
            self._on_solution_vote(current_issue_id, solution_id)

    def _on_code_verification_clicked(self, solution_id: UUID) -> None:
        print(f"Open code verification for solution {solution_id}")

    def _show_torrents_page(self) -> None:
        self._set_active_nav("torrents")
        self.content_stack.setCurrentWidget(self.torrents_page)

    def _show_fleet_page(self) -> None:
        self._set_active_nav("fleet")
        self.content_stack.setCurrentWidget(self.fleet_page)

    def _show_experiment_page(self) -> None:
        self._set_active_nav("experiment")
        self.content_stack.setCurrentWidget(self.experiment_page)

    def _on_experiment_run_requested(
        self,
        dataset: str,
        algorithm: str,
        metric: str,
        rounds: int,
        queries: int,
        gossip: bool,
        hotswap_round: int,
    ) -> None:
        """Spawn a new LTRCommunityThread for this peer's distributed experiment."""
        if self._ltr_thread is not None:
            self._ltr_thread.stop()
            self._ltr_thread.wait(3000)
            self._ltr_thread = None

        thread = LTRCommunityThread(
            dataset_id=dataset,
            algorithm=algorithm,
            metric=metric,
            num_rounds=rounds,
            queries_per_round=queries,
            gossip_enabled=gossip,
            hotswap_round=hotswap_round,
        )
        thread.started_ok.connect(
            self.experiment_page.on_started, type=Qt.ConnectionType.QueuedConnection
        )
        thread.snapshot.connect(
            self.experiment_page.on_snapshot, type=Qt.ConnectionType.QueuedConnection
        )
        thread.log_event.connect(
            self.experiment_page.on_log_event, type=Qt.ConnectionType.QueuedConnection
        )
        thread.finished_ok.connect(
            self.experiment_page.on_finished, type=Qt.ConnectionType.QueuedConnection
        )
        thread.error.connect(
            self.experiment_page.on_error, type=Qt.ConnectionType.QueuedConnection
        )
        thread.finished.connect(self._on_ltr_thread_finished)

        self._ltr_thread = thread
        thread.start()

    def _on_ltr_thread_finished(self) -> None:
        # Allow the next RUN click to spawn a fresh thread
        self._ltr_thread = None

    def stop_ltr_thread(self) -> None:
        """Called from main on shutdown to stop any running experiment cleanly."""
        if self._ltr_thread is not None:
            self._ltr_thread.stop()
            self._ltr_thread.wait(2000)
            self._ltr_thread = None

    def _on_health_data_changed(self) -> None:
        self.torrents_page.load(self._health_thread.get_torrent_data())
        self.fleet_page.load(self._health_thread.get_fleet_data())
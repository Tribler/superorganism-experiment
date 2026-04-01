from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
)

from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes


class VotePanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("variant", "vote-panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.arrow_lbl = QLabel("^")
        self.arrow_lbl.setProperty("role", "vote-arrow")
        self.arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.vote_count_lbl = QLabel("0")
        self.vote_count_lbl.setProperty("role", "vote-count")
        self.vote_count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.vote_caption_lbl = QLabel("Upvotes")
        self.vote_caption_lbl.setProperty("role", "vote-caption")
        self.vote_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.arrow_lbl)
        layout.addWidget(self.vote_count_lbl)
        layout.addWidget(self.vote_caption_lbl)

    def set_votes(self, votes: int) -> None:
        self.vote_count_lbl.setText(str(votes))


class SolutionCard(QFrame):
    voted = pyqtSignal(UUID)
    details_requested = pyqtSignal(UUID)

    def __init__(self, solution_with_votes: SolutionWithVotes, parent: QWidget | None = None):
        super().__init__(parent)

        self.solution_with_votes = solution_with_votes
        self.solution = solution_with_votes.solution

        self.setProperty("variant", "solution-card")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        accent = QFrame()
        accent.setProperty("role", "solution-accent")
        accent.setFixedWidth(5)
        outer.addWidget(accent)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(20)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)

        title_lbl = QLabel(self.solution.title)
        title_lbl.setProperty("role", "solution-title")
        title_lbl.setWordWrap(True)

        desc_lbl = QLabel(self.solution.description)
        desc_lbl.setProperty("role", "solution-description")
        desc_lbl.setWordWrap(True)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(16)

        details_btn = QPushButton("View Details")
        details_btn.setProperty("variant", "link")
        details_btn.clicked.connect(
            lambda: self.details_requested.emit(self.solution.id)
        )

        status_lbl = QLabel(self._build_status_text())
        status_lbl.setProperty("role", "solution-status")

        meta_row.addWidget(details_btn)
        meta_row.addWidget(status_lbl)
        meta_row.addStretch()

        left_col.addWidget(title_lbl)
        left_col.addWidget(desc_lbl)
        left_col.addLayout(meta_row)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(10)
        right_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        votes_lbl = QLabel(str(self.solution_with_votes.votes))
        votes_lbl.setProperty("role", "solution-votes")
        votes_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        votes_caption_lbl = QLabel("Votes")
        votes_caption_lbl.setProperty("role", "solution-votes-caption")
        votes_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        vote_btn = QPushButton("Vote for this solution")
        vote_btn.setProperty("variant", "outline-accent")
        vote_btn.clicked.connect(lambda: self.voted.emit(self.solution.id))

        right_col.addWidget(votes_lbl)
        right_col.addWidget(votes_caption_lbl)
        right_col.addSpacing(6)
        right_col.addWidget(vote_btn)

        body_layout.addLayout(left_col, 1)
        body_layout.addLayout(right_col, 0)

        outer.addWidget(body, 1)

    def _build_status_text(self) -> str:
        if self.solution_with_votes.votes > 0:
            return "Receiving support"
        return "New proposal"


class IssueDetailWidget(QWidget):
    back_clicked = pyqtSignal()
    approved = pyqtSignal(UUID)
    open_create_solution = pyqtSignal(UUID)
    solution_voted = pyqtSignal(UUID, UUID)
    solution_details_requested = pyqtSignal(UUID, UUID)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.current_issue_id: Optional[UUID] = None
        self._current_issue: Optional[IssueWithVotes] = None

        self._build_ui()
        self._set_enabled(False)

    def _build_ui(self) -> None:
        self.setProperty("role", "issue-detail-page")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setProperty("role", "detail-scroll")

        content = QWidget()
        page = QVBoxLayout(content)
        page.setContentsMargins(64, 48, 64, 48)
        page.setSpacing(24)

        back_row = QHBoxLayout()
        back_row.setContentsMargins(0, 0, 0, 0)
        back_row.setSpacing(0)

        self.back_btn = QPushButton("← Back to issues")
        self.back_btn.setProperty("variant", "back-link")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_clicked.emit)

        back_row.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        back_row.addStretch()

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(24)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(4)

        self.meta_row = QHBoxLayout()
        self.meta_row.setContentsMargins(0, 0, 0, 0)
        self.meta_row.setSpacing(6)

        self.status_badge = QLabel("OPEN")
        self.status_badge.setProperty("role", "status-badge")
        self.status_badge.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.issue_id_lbl = QLabel("")
        self.issue_id_lbl.setProperty("role", "issue-id")
        self.issue_id_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.meta_row.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.meta_row.addWidget(self.issue_id_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.meta_row.addStretch()

        self.title_lbl = QLabel("")
        self.title_lbl.setProperty("role", "issue-title")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.title_meta_row = QHBoxLayout()
        self.title_meta_row.setContentsMargins(0, 0, 0, 0)
        self.title_meta_row.setSpacing(3)

        self.created_by_lbl = QLabel("Created by")
        self.created_by_lbl.setProperty("role", "title-meta")

        self.creator_btn = QPushButton("")
        self.creator_btn.setProperty("variant", "creator-link")
        self.creator_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.creator_btn.clicked.connect(self._on_creator_clicked)

        self.title_meta_dot_lbl = QLabel("•")
        self.title_meta_dot_lbl.setProperty("role", "title-meta")

        self.created_at_meta_lbl = QLabel("")
        self.created_at_meta_lbl.setProperty("role", "title-meta")

        self.title_meta_row.addWidget(self.created_by_lbl)
        self.title_meta_row.addWidget(self.creator_btn)
        self.title_meta_row.addWidget(self.title_meta_dot_lbl)
        self.title_meta_row.addWidget(self.created_at_meta_lbl)
        self.title_meta_row.addStretch()

        title_block.addLayout(self.meta_row)
        title_block.addWidget(self.title_lbl)
        title_block.addLayout(self.title_meta_row)

        self.vote_panel = VotePanel()

        header_row.addLayout(title_block, 1)
        header_row.addWidget(self.vote_panel, 0, Qt.AlignmentFlag.AlignTop)

        self.desc_lbl = QLabel("")
        self.desc_lbl.setProperty("role", "issue-description")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.approve_btn = QPushButton("Approve Issue")
        self.approve_btn.setProperty("variant", "primary-accent")
        self.approve_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approve_btn.clicked.connect(self._vote_issue)

        approve_row = QHBoxLayout()
        approve_row.setContentsMargins(0, 0, 0, 0)
        approve_row.setSpacing(0)
        approve_row.addWidget(self.approve_btn, 0, Qt.AlignmentFlag.AlignLeft)
        approve_row.addStretch()

        solutions_header = QHBoxLayout()
        solutions_header.setContentsMargins(0, 0, 0, 0)
        solutions_header.setSpacing(10)

        solutions_title = QLabel("Proposed Solutions")
        solutions_title.setProperty("role", "section-title")

        self.solutions_count_lbl = QLabel("0 Solutions Active")
        self.solutions_count_lbl.setProperty("role", "section-meta")

        self.add_solution_btn = QPushButton("Add Solution")
        self.add_solution_btn.setProperty("variant", "outline-accent")
        self.add_solution_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_solution_btn.clicked.connect(self._open_create_solution)

        solutions_header.addWidget(solutions_title, 0, Qt.AlignmentFlag.AlignVCenter)
        solutions_header.addSpacing(8)
        solutions_header.addWidget(self.solutions_count_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        solutions_header.addStretch()
        solutions_header.addWidget(self.add_solution_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.solutions_layout = QVBoxLayout()
        self.solutions_layout.setContentsMargins(0, 0, 0, 0)
        self.solutions_layout.setSpacing(16)

        self.solutions_wrap = QWidget()
        self.solutions_wrap.setLayout(self.solutions_layout)

        page.addLayout(back_row)
        page.addLayout(header_row)
        page.addWidget(self.desc_lbl)
        page.addLayout(approve_row)
        page.addLayout(solutions_header)
        page.addWidget(self.solutions_wrap)
        page.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _clear_solutions(self) -> None:
        while self.solutions_layout.count():
            item = self.solutions_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()

            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    if child_item.widget():
                        child_item.widget().deleteLater()

    def _set_enabled(self, enabled: bool) -> None:
        self.approve_btn.setEnabled(enabled)
        self.add_solution_btn.setEnabled(enabled)

    def show_issue(
        self,
        issue_with_votes: IssueWithVotes,
        solutions: Optional[list[SolutionWithVotes]] = None,
    ) -> None:
        self._current_issue = issue_with_votes
        self.current_issue_id = issue_with_votes.issue.id

        issue = issue_with_votes.issue

        self.issue_id_lbl.setText(f"ISSUE • {str(issue.id)}")
        self.title_lbl.setText(issue.title)
        self.desc_lbl.setText(issue.description or "No description provided.")
        self.creator_btn.setText(str(issue.creator_id))
        self.created_at_meta_lbl.setText(self._format_created_at(issue.created_at))
        self.vote_panel.set_votes(issue_with_votes.votes)

        if issue_with_votes.votes > 0:
            self.status_badge.setText("OPEN")
        else:
            self.status_badge.setText("NEW")

        self._clear_solutions()

        solutions = solutions or []
        self.solutions_count_lbl.setText(f"{len(solutions)} Solutions Active")

        for solution in solutions:
            card = SolutionCard(solution)
            card.voted.connect(self._on_solution_voted)
            card.details_requested.connect(self._on_solution_details_requested)
            self.solutions_layout.addWidget(card)

        self.solutions_layout.addStretch()
        self._set_enabled(True)

    def _vote_issue(self) -> None:
        if self.current_issue_id is not None:
            self.approved.emit(self.current_issue_id)

    def _on_solution_voted(self, solution_id: UUID) -> None:
        if self.current_issue_id is not None:
            self.solution_voted.emit(self.current_issue_id, solution_id)

    def _on_solution_details_requested(self, solution_id: UUID) -> None:
        if self.current_issue_id is not None:
            self.solution_details_requested.emit(self.current_issue_id, solution_id)

    def _format_created_at(self, created_at) -> str:
        now = datetime.now(timezone.utc)

        if created_at.tzinfo is None:
            delta = now.replace(tzinfo=None) - created_at
        else:
            delta = now - created_at

        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return "just now"

        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"

        days = hours // 24
        if days < 7:
            return f"{days} day{'s' if days != 1 else ''} ago"

        return created_at.strftime("%d %b %Y")

    def _on_creator_clicked(self) -> None:
        if self._current_issue is None:
            return

        print(f"Creator clicked: {self._current_issue.issue.creator_id}")

    def _open_create_solution(self) -> None:
        if self.current_issue_id is not None:
            self.open_create_solution.emit(self.current_issue_id)
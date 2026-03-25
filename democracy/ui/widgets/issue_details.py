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
    QScrollArea, QSizePolicy,
)

from models.DTOs.issue_with_votes import IssueWithVotes
from models.solution import Solution


class VotePanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("votePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.arrow_lbl = QLabel("^")
        self.arrow_lbl.setObjectName("voteArrow")
        self.arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.vote_count_lbl = QLabel("0")
        self.vote_count_lbl.setObjectName("voteCount")
        self.vote_count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.vote_caption_lbl = QLabel("Upvotes")
        self.vote_caption_lbl.setObjectName("voteCaption")
        self.vote_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.arrow_lbl)
        layout.addWidget(self.vote_count_lbl)
        layout.addWidget(self.vote_caption_lbl)

    def set_votes(self, votes: int) -> None:
        self.vote_count_lbl.setText(str(votes))


class SolutionCard(QFrame):
    voted = pyqtSignal(str)
    details_requested = pyqtSignal(str)

    def __init__(self, solution: Solution, parent: QWidget | None = None):
        super().__init__(parent)
        self.solution = solution

        self.setObjectName("solutionCard")
        self.setProperty("highlighted", solution.highlighted)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        accent = QFrame()
        accent.setObjectName("solutionAccent")
        accent.setFixedWidth(5)
        outer.addWidget(accent)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(20)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)

        title_lbl = QLabel(solution.title)
        title_lbl.setObjectName("solutionTitle")
        title_lbl.setWordWrap(True)

        desc_lbl = QLabel(solution.description)
        desc_lbl.setObjectName("solutionDescription")
        desc_lbl.setWordWrap(True)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(16)

        details_btn = QPushButton("View Details")
        details_btn.setObjectName("linkButton")
        details_btn.clicked.connect(lambda: self.details_requested.emit(self.solution.id))

        status_lbl = QLabel(solution.status_text)
        status_lbl.setObjectName("solutionStatus")

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

        votes_lbl = QLabel(str(solution.votes))
        votes_lbl.setObjectName("solutionVotes")
        votes_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        votes_caption_lbl = QLabel("Votes")
        votes_caption_lbl.setObjectName("solutionVotesCaption")
        votes_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        vote_btn = QPushButton("Vote for this solution")
        vote_btn.setObjectName("voteSolutionButton")
        vote_btn.clicked.connect(lambda: self.voted.emit(self.solution.id))

        right_col.addWidget(votes_lbl)
        right_col.addWidget(votes_caption_lbl)
        right_col.addSpacing(6)
        right_col.addWidget(vote_btn)

        body_layout.addLayout(left_col, 1)
        body_layout.addLayout(right_col, 0)

        outer.addWidget(body, 1)


class IssueDetailWidget(QWidget):
    back_clicked = pyqtSignal()
    approved = pyqtSignal(UUID)
    solution_voted = pyqtSignal(UUID, str)
    solution_details_requested = pyqtSignal(UUID, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.current_issue_id: Optional[UUID] = None
        self._current_issue: Optional[IssueWithVotes] = None

        self._build_ui()
        self._apply_styles()
        self._set_enabled(False)

    def _build_ui(self) -> None:
        self.setObjectName("issueDetailWidget")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("detailScroll")

        content = QWidget()
        page = QVBoxLayout(content)
        page.setContentsMargins(64, 48, 64, 48)
        page.setSpacing(24)

        back_row = QHBoxLayout()
        back_row.setContentsMargins(0, 0, 0, 0)
        back_row.setSpacing(0)

        self.back_btn = QPushButton("← Back to issues")
        self.back_btn.setObjectName("backLinkButton")
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
        self.status_badge.setObjectName("statusBadge")

        self.status_badge.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.issue_id_lbl = QLabel("")
        self.issue_id_lbl.setObjectName("issueIdLabel")
        self.issue_id_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.meta_row.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.meta_row.addWidget(self.issue_id_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.meta_row.addStretch()

        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("issueTitle")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.title_meta_row = QHBoxLayout()
        self.title_meta_row.setContentsMargins(0, 0, 0, 0)
        self.title_meta_row.setSpacing(3)

        self.created_by_lbl = QLabel("Created by")
        self.created_by_lbl.setObjectName("titleMeta")

        self.creator_btn = QPushButton("")
        self.creator_btn.setObjectName("creatorLinkButton")
        self.creator_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.creator_btn.clicked.connect(self._on_creator_clicked)

        self.title_meta_dot_lbl = QLabel("•")
        self.title_meta_dot_lbl.setObjectName("titleMeta")

        self.created_at_meta_lbl = QLabel("")
        self.created_at_meta_lbl.setObjectName("titleMeta")

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
        self.desc_lbl.setObjectName("issueDescription")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.approve_btn = QPushButton("Approve Issue")
        self.approve_btn.setObjectName("approveButton")
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
        solutions_title.setObjectName("sectionTitle")

        self.solutions_count_lbl = QLabel("0 Solutions Active")
        self.solutions_count_lbl.setObjectName("sectionMeta")

        solutions_header.addWidget(solutions_title)
        solutions_header.addStretch()
        solutions_header.addWidget(self.solutions_count_lbl)

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

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#issueDetailWidget {
                background: #0b1220;
                color: #e5e7eb;
            }

            QLabel#statusBadge {
                background-color: rgba(139, 92, 246, 0.12);
                color: #c4b5fd;
                border: 1px solid rgba(139, 92, 246, 0.35);
                border-radius: 10px;
                padding-left: 10px;
                padding-right: 10px;
                min-height: 20px;
                max-height: 20px;
                font-size: 9px;
                font-weight: 800;
                letter-spacing: 1.2px;
            }

            QLabel#issueIdLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 1px;
            }

            QLabel#issueTitle {
                color: white;
                margin: 0;
                padding: 0;
                font-size: 50px;
                font-weight: 800;
                line-height: 1.15;
            }

            QFrame#votePanel {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 18px;
                min-width: 160px;
            }

            QLabel#voteCount {
                color: white;
                font-size: 30px;
                font-weight: 800;
            }

            QLabel#voteCaption {
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.2px;
                text-transform: uppercase;
            }

            QLabel#sectionTitle {
                color: white;
                font-size: 20px;
                font-weight: 800;
            }

            QLabel#sectionMeta {
                color: #94a3b8;
                font-size: 13px;
                font-weight: 500;
            }

            QLabel#issueDescription {
                background: transparent;
                color: #cbd5e1;
                font-size: 16px;
                line-height: 1.7;
                margin: 0;
                padding: 0;
            }

            QLabel#metaInfo {
                color: #94a3b8;
                font-size: 12px;
            }

            QFrame#solutionCard {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 18px;
            }

            QFrame#solutionCard:hover {
                background: rgba(255, 255, 255, 0.05);
            }

            QFrame#solutionAccent {
                background: rgba(148, 163, 184, 0.18);
                border-top-left-radius: 18px;
                border-bottom-left-radius: 18px;
            }

            QFrame#solutionCard[highlighted="true"] QFrame#solutionAccent {
                background: #8b5cf6;
            }

            QLabel#solutionTitle {
                color: white;
                font-size: 20px;
                font-weight: 800;
            }

            QLabel#solutionDescription {
                color: #cbd5e1;
                font-size: 14px;
                line-height: 1.5;
            }

            QPushButton#linkButton {
                background: transparent;
                border: none;
                color: #a78bfa;
                padding: 0;
                font-size: 13px;
                font-weight: 700;
                text-align: left;
            }

            QPushButton#linkButton:hover {
                color: #c4b5fd;
                text-decoration: underline;
            }

            QLabel#solutionStatus {
                color: #94a3b8;
                font-size: 12px;
            }

            QLabel#solutionVotes {
                color: white;
                font-size: 28px;
                font-weight: 800;
            }

            QLabel#solutionVotesCaption {
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.2px;
                text-transform: uppercase;
            }

            QPushButton#voteSolutionButton {
                background: transparent;
                color: #a78bfa;
                border: 1px solid rgba(139, 92, 246, 0.4);
                border-radius: 12px;
                padding: 12px 18px;
                font-size: 13px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#voteSolutionButton:hover {
                background: rgba(139, 92, 246, 0.10);
            }

            QScrollArea#detailScroll {
                border: none;
                background: transparent;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background: rgba(148, 163, 184, 0.35);
                border-radius: 5px;
                min-height: 24px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
                border: none;
            }
            
            QPushButton#backLinkButton {
                background: transparent;
                border: none;
                color: #8b5cf6;
                padding: 0;
                font-size: 13px;
                font-weight: 500;
                text-align: left;
            }

            QPushButton#backLinkButton:hover {
                color: #a78bfa;
            }

            QPushButton#backLinkButton:pressed {
                color: #c4b5fd;
            }
            
            QLabel#titleMeta {
                color: #94a3b8;
                font-size: 13px;
                font-weight: 500;
            }
            
            QPushButton#creatorLinkButton {
                background: transparent;
                border: none;
                color: #b6a0ff;
                padding: 0;
                margin: 0;
                font-size: 13px;
                font-weight: 600;
                text-align: left;
            }
            
            QPushButton#creatorLinkButton:hover {
                color: #c4b5fd;
                text-decoration: underline;
            }
            
            QPushButton#creatorLinkButton:pressed {
                color: #ddd6fe;
            }
            
            QFrame#votePanel {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 18px;
                min-width: 120px;
            }
            
            QLabel#voteArrow {
                color: #8b5cf6;
                font-size: 24px;
                font-weight: 500;
                margin: 0;
                padding: 0;
            }
            
            QLabel#voteCount {
                color: white;
                font-size: 28px;
                font-weight: 800;
            }
            
            QLabel#voteCaption {
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.2px;
                text-transform: uppercase;
            }
            
            QPushButton#approveButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed,
                    stop:1 #6366f1
                );
                color: white;
                border: none;
                border-radius: 12px;
                padding: 12px 18px;
                font-size: 13px;
                font-weight: 700;
                text-align: center;
            }
            
            QPushButton#approveButton:hover:!disabled {
                background: #8b5cf6;
            }
            
            QPushButton#approveButton:disabled {
                background: rgba(255, 255, 255, 0.10);
                color: rgba(255, 255, 255, 0.45);
            }
        """)

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

    def show_issue(
        self,
        issue_with_votes: IssueWithVotes,
        solutions: Optional[list[Solution]] = None,
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

    def _on_solution_voted(self, solution_id: str) -> None:
        if self.current_issue_id is not None:
            self.solution_voted.emit(self.current_issue_id, solution_id)

    def _on_solution_details_requested(self, solution_id: str) -> None:
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
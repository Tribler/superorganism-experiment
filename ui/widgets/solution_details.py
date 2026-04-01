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

from democracy.models.DTOs.solution_with_votes import SolutionWithVotes


class SolutionVotePanel(QFrame):
    voted = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("variant", "solution-vote-panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        self.status_kicker_lbl = QLabel("CURRENT STATUS")
        self.status_kicker_lbl.setProperty("role", "solution-side-kicker")

        self.vote_count_lbl = QLabel("0")
        self.vote_count_lbl.setProperty("role", "solution-side-votes")

        self.status_lbl = QLabel("ACTIVE VOTING")
        self.status_lbl.setProperty("role", "solution-side-status")

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)
        top_row.addWidget(self.vote_count_lbl)
        top_row.addWidget(self.status_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        top_row.addStretch()

        self.progress_track = QFrame()
        self.progress_track.setProperty("role", "solution-progress-track")
        progress_layout = QHBoxLayout(self.progress_track)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(0)

        self.progress_fill = QFrame()
        self.progress_fill.setProperty("role", "solution-progress-fill")
        self.progress_fill.setFixedWidth(120)

        progress_layout.addWidget(self.progress_fill, 0)
        progress_layout.addStretch()

        self.quorum_lbl = QLabel("Quorum: 65% Required")
        self.quorum_lbl.setProperty("role", "solution-side-meta")
        self.quorum_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.vote_btn = QPushButton("Vote for this solution")
        self.vote_btn.setProperty("variant", "primary")
        self.vote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vote_btn.clicked.connect(self.voted.emit)

        self.helper_lbl = QLabel(
            "By voting, you certify that you have reviewed the technical "
            "specifications and impact reports."
        )
        self.helper_lbl.setProperty("role", "solution-side-helper")
        self.helper_lbl.setWordWrap(True)
        self.helper_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.status_kicker_lbl)
        layout.addLayout(top_row)
        layout.addWidget(self.progress_track)
        layout.addWidget(self.quorum_lbl)
        layout.addSpacing(10)
        layout.addWidget(self.vote_btn)
        layout.addWidget(self.helper_lbl)

    def set_votes(self, votes: int) -> None:
        self.vote_count_lbl.setText(str(votes))

    def set_vote_button_enabled(self, enabled: bool) -> None:
        self.vote_btn.setEnabled(enabled)


class CodeVerificationCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("variant", "verification-card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self.icon_frame = QFrame()
        self.icon_frame.setProperty("role", "verification-icon-wrap")
        self.icon_frame.setFixedSize(52, 52)

        icon_layout = QVBoxLayout(self.icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(0)

        self.icon_lbl = QLabel("⌘")
        self.icon_lbl.setProperty("role", "verification-icon")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(self.icon_lbl)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)

        self.title_lbl = QLabel("Code Verification")
        self.title_lbl.setProperty("role", "verification-title")

        self.subtitle_btn = QPushButton("View GitHub Pull Request #142")
        self.subtitle_btn.setProperty("variant", "link")
        self.subtitle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subtitle_btn.clicked.connect(self.clicked.emit)

        text_col.addWidget(self.title_lbl)
        text_col.addWidget(self.subtitle_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.open_btn = QPushButton("↗")
        self.open_btn.setProperty("variant", "icon-link")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.clicked.emit)

        layout.addWidget(self.icon_frame, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_col, 1)
        layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def set_link_text(self, text: str) -> None:
        self.subtitle_btn.setText(text)


class SolutionDetailWidget(QWidget):
    back_clicked = pyqtSignal()
    voted = pyqtSignal(UUID)
    code_verification_clicked = pyqtSignal(UUID)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.current_solution_id: Optional[UUID] = None
        self._current_solution: Optional[SolutionWithVotes] = None

        self._build_ui()
        self._set_enabled(False)

    def _build_ui(self) -> None:
        self.setProperty("role", "solution-detail-page")

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

        self.back_btn = QPushButton("← Back to issue")
        self.back_btn.setProperty("variant", "back-link")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_clicked.emit)

        back_row.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        back_row.addStretch()

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        self.solution_id_lbl = QLabel("")
        self.solution_id_lbl.setProperty("role", "status-badge")

        self.meta_dot_lbl = QLabel("•")
        self.meta_dot_lbl.setProperty("role", "title-meta")

        self.created_at_lbl = QLabel("")
        self.created_at_lbl.setProperty("role", "title-meta")

        meta_row.addWidget(self.solution_id_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.meta_dot_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.created_at_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch()

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(36)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(20)

        self.title_lbl = QLabel("")
        self.title_lbl.setProperty("role", "issue-title")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        author_row = QHBoxLayout()
        author_row.setContentsMargins(0, 0, 0, 0)
        author_row.setSpacing(16)

        proposed_by_col = QVBoxLayout()
        proposed_by_col.setContentsMargins(0, 0, 0, 0)
        proposed_by_col.setSpacing(4)

        proposed_by_kicker = QLabel("PROPOSED BY")
        proposed_by_kicker.setProperty("role", "solution-meta-kicker")

        self.creator_btn = QPushButton("")
        self.creator_btn.setProperty("variant", "creator-link")
        self.creator_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        proposed_by_col.addWidget(proposed_by_kicker)
        proposed_by_col.addWidget(self.creator_btn, 0, Qt.AlignmentFlag.AlignLeft)

        created_col = QVBoxLayout()
        created_col.setContentsMargins(0, 0, 0, 0)
        created_col.setSpacing(4)

        created_kicker = QLabel("TIME SINCE CREATION")
        created_kicker.setProperty("role", "solution-meta-kicker")

        self.time_since_lbl = QLabel("")
        self.time_since_lbl.setProperty("role", "title-meta")

        created_col.addWidget(created_kicker)
        created_col.addWidget(self.time_since_lbl)

        author_row.addLayout(proposed_by_col)
        author_row.addSpacing(20)
        author_row.addLayout(created_col)
        author_row.addStretch()

        self.section_title_lbl = QLabel("TECHNICAL DESCRIPTION")
        self.section_title_lbl.setProperty("role", "solution-section-kicker")

        self.desc_lbl = QLabel("")
        self.desc_lbl.setProperty("role", "issue-description")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.verification_card = CodeVerificationCard()
        self.verification_card.clicked.connect(self._on_code_verification_clicked)

        left_col.addLayout(meta_row)
        left_col.addWidget(self.title_lbl)
        left_col.addLayout(author_row)
        left_col.addSpacing(8)
        left_col.addWidget(self.section_title_lbl)
        left_col.addWidget(self.desc_lbl)
        left_col.addSpacing(10)
        left_col.addWidget(self.verification_card)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(20)

        self.vote_panel = SolutionVotePanel()
        self.vote_panel.voted.connect(self._vote_solution)

        right_col.addWidget(self.vote_panel)
        right_col.addStretch()

        header_row.addLayout(left_col, 1)
        header_row.addLayout(right_col, 0)

        page.addLayout(back_row)
        page.addLayout(header_row)
        page.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _set_enabled(self, enabled: bool) -> None:
        self.vote_panel.set_vote_button_enabled(enabled)

    def show_solution(self, solution_with_votes: SolutionWithVotes) -> None:
        self._current_solution = solution_with_votes
        self.current_solution_id = solution_with_votes.solution.id

        solution = solution_with_votes.solution

        self.solution_id_lbl.setText(f"PROPOSAL #{str(solution.id)[:8]}")
        self.created_at_lbl.setText(
            f"Published {solution.created_at.strftime('%b %d, %Y')}"
        )
        self.title_lbl.setText(solution.title)
        self.creator_btn.setText(str(solution.creator_id))
        self.time_since_lbl.setText(self._format_created_at(solution.created_at))
        self.desc_lbl.setText(solution.description or "No description provided.")
        self.vote_panel.set_votes(solution_with_votes.votes)

        self._set_enabled(True)

    def _vote_solution(self) -> None:
        if self.current_solution_id is not None:
            self.voted.emit(self.current_solution_id)

    def _on_code_verification_clicked(self) -> None:
        if self.current_solution_id is not None:
            self.code_verification_clicked.emit(self.current_solution_id)

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
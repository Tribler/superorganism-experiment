from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)

from compat import StrEnum
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes
from ui.constants import SOLUTION_VOTE_TARGET

_UNSET = object()


class SolutionSidePanelStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class SolutionFundingPanelState:
    has_campaign: bool
    can_create_pledge: bool = False
    raised_sats: int | None = None
    target_sats: int | None = None
    valid_pledge_count: int | None = None
    deadline_height: int | None = None
    payout_address: str = ""
    status: SolutionSidePanelStatus | None = None


class SolutionSidePanel(QFrame):
    action_clicked = Signal()

    def __init__(
        self,
        *,
        kicker_text: str,
        primary_value_text: str,
        status: SolutionSidePanelStatus | None,
        meta_text: str,
        action_text: str,
        helper_text: str,
        action_enabled: bool,
        progress_ratio: float,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setProperty("variant", "solution-side-panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        self.status_kicker_lbl = QLabel(kicker_text)
        self.status_kicker_lbl.setProperty("role", "solution-side-kicker")

        self.primary_value_lbl = QLabel(primary_value_text)
        self.primary_value_lbl.setProperty("role", "solution-side-votes")

        self.status_pill_lbl = QLabel("")
        self.status_pill_lbl.setProperty("role", "solution-side-status-pill")
        self.status_pill_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)
        top_row.addWidget(self.status_kicker_lbl, 0, Qt.AlignmentFlag.AlignLeft)
        top_row.addStretch()
        top_row.addWidget(self.status_pill_lbl, 0, Qt.AlignmentFlag.AlignRight)

        self.progress_track = QFrame()
        self.progress_track.setProperty("role", "solution-progress-track")
        progress_layout = QHBoxLayout(self.progress_track)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(0)

        self.progress_fill = QFrame()
        self.progress_fill.setProperty("role", "solution-progress-fill")
        self.progress_fill.setFixedWidth(0)

        progress_layout.addWidget(self.progress_fill, 0)
        progress_layout.addStretch()

        self.meta_lbl = QLabel(meta_text)
        self.meta_lbl.setProperty("role", "solution-side-meta")
        self.meta_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.action_btn = QPushButton(action_text)
        self.action_btn.setProperty("variant", "primary")
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self.action_clicked.emit)

        self.helper_lbl = QLabel(helper_text)
        self.helper_lbl.setProperty("role", "solution-side-helper")
        self.helper_lbl.setWordWrap(True)
        self.helper_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(top_row)
        layout.addWidget(self.primary_value_lbl)
        layout.addWidget(self.progress_track)
        layout.addWidget(self.meta_lbl)
        layout.addSpacing(10)
        layout.addWidget(self.action_btn)
        layout.addWidget(self.helper_lbl)

        self._progress_ratio = 0.0
        self.set_action_button_enabled(action_enabled)
        self.set_status(status)
        self.set_progress_ratio(progress_ratio)

    def set_panel_content(
        self,
        *,
        primary_value_text: str | None = None,
        status: SolutionSidePanelStatus | None | object = _UNSET,
        helper_text: str | None = None,
        action_enabled: bool | None = None,
        progress_ratio: float | None = None,
    ) -> None:
        if primary_value_text is not None:
            self.set_primary_value_text(primary_value_text)
        if status is not _UNSET:
            self.set_status(status)
        if helper_text is not None:
            self.set_helper_text(helper_text)
        if action_enabled is not None:
            self.set_action_button_enabled(action_enabled)
        if progress_ratio is not None:
            self.set_progress_ratio(progress_ratio)

    def set_primary_value_text(self, text: str) -> None:
        self.primary_value_lbl.setText(text)

    def set_status(self, status: SolutionSidePanelStatus | None) -> None:
        if status is None:
            self.status_pill_lbl.clear()
            self.status_pill_lbl.hide()
            return

        self.status_pill_lbl.setText(status.value.upper())
        self.status_pill_lbl.setProperty("status", status)
        self.status_pill_lbl.style().unpolish(self.status_pill_lbl)
        self.status_pill_lbl.style().polish(self.status_pill_lbl)
        self.status_pill_lbl.show()

    def set_helper_text(self, text: str) -> None:
        self.helper_lbl.setText(text)

    def set_action_button_enabled(self, enabled: bool) -> None:
        self.action_btn.setEnabled(enabled)

    def set_meta_text(self, text: str) -> None:
        self.meta_lbl.setText(text)

    def set_progress_ratio(self, ratio: float) -> None:
        self._progress_ratio = max(0.0, min(1.0, ratio))
        self._apply_progress_ratio()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_progress_ratio()

    def _apply_progress_ratio(self) -> None:
        track_width = self.progress_track.contentsRect().width()
        if track_width <= 0:
            track_width = self.progress_track.width()
        self.progress_fill.setFixedWidth(int(track_width * self._progress_ratio))


class SolutionVotePanel(SolutionSidePanel):
    voted = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            kicker_text="SOLUTION VOTES",
            primary_value_text="0",
            status=SolutionSidePanelStatus.OPEN,
            meta_text=f"Target: {SOLUTION_VOTE_TARGET} votes",
            action_text="Vote for this solution",
            helper_text=(
                "By voting, you certify that you have reviewed the technical "
                "specifications and impact reports."
            ),
            action_enabled=False,
            progress_ratio=0.0,
            parent=parent,
        )
        self.action_clicked.connect(self.voted.emit)

    def set_votes(self, votes: int) -> None:
        status = (
            SolutionSidePanelStatus.COMPLETED
            if votes >= SOLUTION_VOTE_TARGET
            else SolutionSidePanelStatus.OPEN
        )
        self.set_panel_content(
            primary_value_text=str(votes),
            status=status,
            progress_ratio=self._progress_ratio_for_votes(votes),
        )

    def set_vote_button_enabled(self, enabled: bool) -> None:
        self.set_action_button_enabled(enabled)

    @staticmethod
    def _progress_ratio_for_votes(votes: int) -> float:
        if SOLUTION_VOTE_TARGET <= 0:
            return 0.0
        return votes / SOLUTION_VOTE_TARGET


class SolutionFundingPanel(SolutionSidePanel):
    create_pledge_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            kicker_text="FUNDING POOL",
            primary_value_text="--",
            status=None,
            meta_text="Target: --",
            action_text="Create pledge",
            helper_text="Funding campaign details will appear here.",
            action_enabled=False,
            progress_ratio=0.0,
            parent=parent,
        )
        self._target_sats: int | None = None
        self.action_clicked.connect(self.create_pledge_requested.emit)

    def show_placeholder(self) -> None:
        self._set_target_sats(None)
        self.set_panel_content(
            primary_value_text="--",
            status=None,
            helper_text="Funding campaign details will appear here.",
            action_enabled=False,
            progress_ratio=0.0,
        )

    def show_state(self, state: SolutionFundingPanelState) -> None:
        if not state.has_campaign:
            self.show_placeholder()
            return

        raised_sats = state.raised_sats if state.raised_sats is not None else 0
        target_sats = state.target_sats if state.target_sats is not None else 0
        pledge_count = state.valid_pledge_count if state.valid_pledge_count is not None else 0
        deadline_text = (
            f"Deadline: block {state.deadline_height}"
            if state.deadline_height is not None
            else "Deadline: --"
        )
        payout_text = (
            state.payout_address
            if len(state.payout_address) <= 20
            else f"{state.payout_address[:10]}...{state.payout_address[-8:]}"
        )

        fill_ratio = (raised_sats / target_sats) if target_sats > 0 else 0.0
        self._set_target_sats(state.target_sats)
        self.set_panel_content(
            primary_value_text=self._format_sats(raised_sats),
            status=state.status,
            helper_text=f"{deadline_text}\nPledges: {pledge_count}\nPayout: {payout_text or '--'}",
            action_enabled=state.can_create_pledge,
            progress_ratio=fill_ratio,
        )

    @staticmethod
    def _format_sats(value_sats: int) -> str:
        return f"{value_sats:,} sats"

    def _set_target_sats(self, target_sats: int | None) -> None:
        if self._target_sats == target_sats:
            return

        self._target_sats = target_sats
        self.set_meta_text(
            f"Target: {self._format_sats(target_sats)}"
            if target_sats is not None
            else "Target: --"
        )


class CodeVerificationCard(QFrame):
    clicked = Signal()

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
    back_clicked = Signal()
    voted = Signal(object)
    code_verification_clicked = Signal(object)
    create_pledge_requested = Signal(object)

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
        self.funding_panel = SolutionFundingPanel()
        self.funding_panel.create_pledge_requested.connect(self._request_create_pledge)

        right_col.addWidget(self.vote_panel)
        right_col.addWidget(self.funding_panel)
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

    def show_solution(
        self,
        solution_with_votes: SolutionWithVotes,
        funding_state: SolutionFundingPanelState | None = None,
    ) -> None:
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
        if funding_state is None:
            self.funding_panel.show_placeholder()
        else:
            self.funding_panel.show_state(funding_state)

        self._set_enabled(True)

    def _vote_solution(self) -> None:
        if self.current_solution_id is not None:
            self.voted.emit(self.current_solution_id)

    def _on_code_verification_clicked(self) -> None:
        if self.current_solution_id is not None:
            self.code_verification_clicked.emit(self.current_solution_id)

    def _request_create_pledge(self) -> None:
        if self.current_solution_id is not None:
            self.create_pledge_requested.emit(self.current_solution_id)

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

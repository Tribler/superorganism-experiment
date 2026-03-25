from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from constants import ISSUE_THRESHOLD
from models.DTOs.issue_with_votes import IssueWithVotes


class IssueTableModel(QAbstractTableModel):
    HEADERS = ["Issue ID", "Title", "Creator", "Threshold", "Votes", "Progress", "Status"]

    def __init__(self, issues: Optional[List[IssueWithVotes]] = None, parent=None):
        super().__init__(parent)
        self._issues: List[IssueWithVotes] = issues or []

    # --- Qt model basics ---
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._issues)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        col = index.column()
        i = self._issues[index.row()]
        issue = i.issue
        progress = min(100, int((i.votes / ISSUE_THRESHOLD) * 100))
        status = "Passed" if i.votes >= ISSUE_THRESHOLD else "Open"

        # Raw values for this row
        values = [
            str(issue.id)[:8] + "...",
            issue.title,
            str(issue.creator_id)[:24] + "...",
            ISSUE_THRESHOLD,
            i.votes,
            progress,
            status,
        ]

        if role == Qt.ItemDataRole.DisplayRole:
            return str(values[col])

        if role == Qt.ItemDataRole.UserRole:
            return issue.id

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (3, 4):  # threshold + votes
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 6:
            if status == "Passed":
                return QColor("#34d399")
            return QColor("#cbd5e1")

        return None

    # --- Convenience API for your widget ---
    def set_issues(self, issues: List[IssueWithVotes]) -> None:
        self.beginResetModel()
        self._issues = list(issues)
        self.endResetModel()

    def issue_id_at(self, row: int) -> Optional[UUID]:
        if 0 <= row < len(self._issues):
            return self._issues[row].issue.id
        return None
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from models.DTOs.election_with_votes import ElectionWithVotes


class ElectionListModel(QAbstractTableModel):
    HEADERS = ["Election ID", "Title", "Creator", "Threshold", "Votes"]

    def __init__(self, elections: Optional[List[ElectionWithVotes]] = None, parent=None):
        super().__init__(parent)
        self._elections: List[ElectionWithVotes] = elections or []

    # --- Qt model basics ---
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._elections)

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

        row = index.row()
        col = index.column()
        e = self._elections[row]

        # Raw values for this row
        values = [
            e.election.id,
            e.election.title,
            str(e.election.creator_id),
            e.election.threshold,
            e.votes,
        ]

        if role == Qt.ItemDataRole.DisplayRole:
            v = values[col]
            return str(v)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (3, 4):  # threshold + votes
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Optional: allow consumers to retrieve election_id via UserRole
        if role == Qt.ItemDataRole.UserRole:
            return e.election.id

        return None

    # --- Convenience API for your widget ---
    def setElections(self, elections: List[ElectionWithVotes]) -> None:
        self.beginResetModel()
        self._elections = list(elections)
        self.endResetModel()

    def election_id_at(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._elections):
            return self._elections[row].election.id
        return None
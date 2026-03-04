from __future__ import annotations

from typing import Callable, List, Optional

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal

from models.DTOs.election_with_votes import ElectionWithVotes

class ElectionListWidget(QWidget):
    selected = pyqtSignal(str)

    """
    Widget that displays a list of elections in a treeview.
    Calls on_select(election_id) when an election is selected.

    Args:
        on_select: Callback function when an election is selected.
        parent: Parent widget.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._row_to_election_id: dict[int, str] = {}

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Election ID", "Title", "Creator", "Threshold", "Votes"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.table.itemSelectionChanged.connect(self._on_select)

        layout.addWidget(self.table)

    def load(self, elections: List[ElectionWithVotes]):
        """
        Loads the list of elections into the treeview.

        :param elections: List of ElectionWithVotes to load.
        :return: None
        """
        self.table.setRowCount(0)
        self._row_to_election_id.clear()

        for row_idx, e in enumerate(elections):
            self.table.insertRow(row_idx)
            self._row_to_election_id[row_idx] = e.election.id

            values = [
                e.election.id,
                e.election.title,
                str(e.election.creator_id),
                str(e.election.threshold),
                str(e.votes),
            ]
            for col_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col_idx in (3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()

    def _on_select(self):
        """
        Handles selection of an election in the treeview.

        :return: None
        """
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return

        row = selected[0].row()

        election_id = self._row_to_election_id.get(row)
        if election_id:
            self.selected.emit(str(election_id))
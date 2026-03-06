from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableView

from models.DTOs.election_with_votes import ElectionWithVotes
from ui.widgets.election_list_model import ElectionListModel


class ElectionListWidget(QWidget):
    """
    Widget that displays a list of elections using Qt Model/View.
    Emits selected(election_id) when a row is selected.
    """
    selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        self.model = ElectionListModel()
        self.table = QTableView()
        self.table.setModel(self.model)

        # Selection behavior similar to your old widget
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)

        # Optional: nicer UX
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)  # can turn on later (see note below)

        # Emit selection when it changes
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self.table)

    def load(self, elections: List[ElectionWithVotes]) -> None:
        self.model.setElections(elections)
        self.table.resizeColumnsToContents()

    def _on_selection_changed(self, _selected, _deselected) -> None:
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return
        row = idxs[0].row()
        election_id = self.model.election_id_at(row)
        if election_id:
            self.selected.emit(election_id)
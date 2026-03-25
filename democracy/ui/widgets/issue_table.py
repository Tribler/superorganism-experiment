from __future__ import annotations

from typing import Optional
from uuid import UUID

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableView,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QApplication,
)

from models.DTOs.issue_with_votes import IssueWithVotes
from ui.widgets.issue_table_model import IssueTableModel
from ui.widgets.issue_filter_proxy_model import IssueFilterProxyModel


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        value = index.data(Qt.ItemDataRole.DisplayRole)
        if value is None:
            return super().paint(painter, option, index)

        try:
            percent = int(float(value))
        except (TypeError, ValueError):
            percent = 0

        progress = QStyleOptionProgressBar()
        progress.rect = option.rect.adjusted(12, 10, -12, -10)
        progress.minimum = 0
        progress.maximum = 100
        progress.progress = max(0, min(100, percent))
        progress.textVisible = False

        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, progress, painter)


class IssueTableWidget(QWidget):
    selected = pyqtSignal(UUID)
    activated = pyqtSignal(UUID)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.model = IssueTableModel(parent=self)
        self.proxy = IssueFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.table.setItemDelegateForColumn(5, ProgressDelegate(self.table))
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_double_clicked)
        self.table.activated.connect(self._on_double_clicked)

        layout.addWidget(self.table)

        self.table.setStyleSheet("""
            QTableView {
                background: transparent;
                color: white;
                border: none;
                gridline-color: transparent;
                selection-background-color: rgba(59,130,246,0.18);
                selection-color: white;
            }

            QHeaderView::section {
                background: rgba(148,163,184,0.35);
                color: white;
                border: none;
                padding: 16px 14px;
                font-weight: 600;
            }
        """)

    def load(self, issues: list[IssueWithVotes]) -> None:
        self.model.set_issues(issues)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def set_search_text(self, text: str) -> None:
        self.proxy.set_search_text(text)

    def set_filter_mode(self, mode: str) -> None:
        self.proxy.set_filter_mode(mode)

    def _emit_for_proxy_row(self, proxy_row: int, signal) -> None:
        proxy_index = self.proxy.index(proxy_row, 0)
        source_index = self.proxy.mapToSource(proxy_index)

        if not source_index.isValid():
            return

        issue_id = self.model.index(source_index.row(), 0).data(Qt.ItemDataRole.UserRole)

        if issue_id:
            signal.emit(issue_id)

    def _on_selection_changed(self, _selected, _deselected) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._emit_for_proxy_row(rows[0].row(), self.selected)

    def _on_double_clicked(self, index) -> None:
        if not index.isValid():
            return

        self._emit_for_proxy_row(index.row(), self.activated)
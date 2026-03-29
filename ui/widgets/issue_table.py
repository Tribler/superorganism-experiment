from __future__ import annotations

from typing import Optional
from uuid import UUID

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableView,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QApplication, QHeaderView,
)

from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from ui.widgets.issue_table_model import IssueTableModel
from ui.widgets.issue_filter_proxy_model import IssueFilterProxyModel
from ui.widgets.table_utils import apply_shared_table_config


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

        QApplication.style().drawControl(
            QStyle.ControlElement.CE_ProgressBar,
            progress,
            painter,
        )


class IssueTableWidget(QWidget):
    selected = pyqtSignal(UUID)
    activated = pyqtSignal(UUID)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("role", "issue-table-widget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.model = IssueTableModel(parent=self)
        self.proxy = IssueFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setProperty("variant", "data-table")
        self.table.setModel(self.proxy)

        apply_shared_table_config(self.table)

        self.table.setItemDelegateForColumn(5, ProgressDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_double_clicked)
        self.table.activated.connect(self._on_double_clicked)

        layout.addWidget(self.table)

    def load(self, issues: list[IssueWithVotes]) -> None:
        self.model.set_issues(issues)
        self.table.resizeColumnsToContents()

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
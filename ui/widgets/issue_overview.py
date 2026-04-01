from __future__ import annotations

from typing import Optional
from uuid import UUID

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QPushButton,
    QLabel,
    QLineEdit,
    QComboBox,
)

from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from ui.widgets.issue_table import IssueTableWidget


class IssuesOverviewWidget(QWidget):
    create_clicked = pyqtSignal()
    search_changed = pyqtSignal(str)
    filter_changed = pyqtSignal(str)
    issue_selected = pyqtSignal(UUID)
    issue_activated = pyqtSignal(UUID)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("issuesPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        header = QHBoxLayout()

        self.title_label = QLabel("Issues")
        self.title_label.setProperty("role", "page-title")

        self.create_btn = QPushButton("Create New Issue")
        self.create_btn.setProperty("variant", "primary")
        self.create_btn.clicked.connect(self.create_clicked)

        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.create_btn)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(14)

        self.search_input = QLineEdit()
        self.search_input.setProperty("variant", "default")
        self.search_input.setPlaceholderText("Search")
        self.search_input.textChanged.connect(self.search_changed)

        self.filter_combo = QComboBox()
        self.filter_combo.setProperty("variant", "default")
        self.filter_combo.addItems(["All", "Open", "Passed", "Needs Votes"])
        self.filter_combo.currentTextChanged.connect(self.filter_changed)

        toolbar.addWidget(self.search_input, 1)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Filter by:"))
        toolbar.addWidget(self.filter_combo)

        table_card = QFrame()
        table_card.setProperty("variant", "card")

        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.issue_table = IssueTableWidget()
        self.issue_table.selected.connect(self.issue_selected)
        self.issue_table.activated.connect(self.issue_activated)

        table_layout.addWidget(self.issue_table)

        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(table_card, 1)

    def load(self, issues: list[IssueWithVotes]) -> None:
        self.issue_table.load(issues)

    def set_search_text(self, text: str) -> None:
        self.search_input.setText(text)

    def set_filter_mode(self, mode: str) -> None:
        index = self.filter_combo.findText(mode)
        if index >= 0:
            self.filter_combo.setCurrentIndex(index)

    def apply_search_filter(self, text: str) -> None:
        self.issue_table.set_search_text(text)

    def apply_status_filter(self, mode: str) -> None:
        self.issue_table.set_filter_mode(mode)
# ui/widgets/create_issue_dialog.py
from __future__ import annotations

import uuid

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
)

from models.issue import Issue


class CreateIssueDialog(QDialog):
    created = pyqtSignal(Issue)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Issue")
        self.resize(500, 220)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit()
        self.description_edit = QLineEdit()

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 10_000_000)
        self.threshold_spin.setValue(50)

        form.addRow("Title", self.title_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Threshold", self.threshold_spin)

        actions = QHBoxLayout()
        actions.addStretch()

        cancel_btn = QPushButton("Cancel")
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self._create)
        cancel_btn.clicked.connect(self.reject)

        actions.addWidget(cancel_btn)
        actions.addWidget(create_btn)

        root.addLayout(form)
        root.addLayout(actions)

    def _create(self) -> None:
        issue = Issue(
            id=str(uuid.uuid4()),
            title=self.title_edit.text(),
            description=self.description_edit.text(),
            threshold=int(self.threshold_spin.value()),
        )
        self.created.emit(issue)
        self.accept()
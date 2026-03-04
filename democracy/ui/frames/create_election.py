from __future__ import annotations

import uuid
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QGridLayout,
)

from models.election import Election


class CreateElectionFrame(QWidget):
    """
    Widget for creating an election. Calls on_create(election) on submit.

    Args:
        on_create: Callback function when an election is created.
        parent: Parent widget.
    """
    def __init__(self, on_create: Optional[Callable[[Election], None]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.on_create = on_create

        layout = QGridLayout(self)

        layout.addWidget(QLabel("Title:"), 0, 0)
        self.title_edit = QLineEdit()
        layout.addWidget(self.title_edit, 0, 1)

        layout.addWidget(QLabel("Description:"), 1, 0)
        self.description_edit = QLineEdit()
        layout.addWidget(self.description_edit, 1, 1)

        layout.addWidget(QLabel("Threshold:"), 2, 0)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 10_000_000)
        self.threshold_spin.setValue(50)
        layout.addWidget(self.threshold_spin, 2, 1)

        self.create_btn = QPushButton("Create")
        self.create_btn.clicked.connect(self._create)
        layout.addWidget(self.create_btn, 3, 0, 1, 2)

        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)

    def _create(self):
        """
        Handles creation of a new election and calls the on_create callback.

        :return: None
        """
        e = Election(
            id=str(uuid.uuid4()),
            title=self.title_edit.text(),
            description=self.description_edit.text(),
            threshold=int(self.threshold_spin.value())
        )

        if self.on_create:
            self.on_create(e)

        # Clear fields
        self.title_edit.setText("")
        self.description_edit.setText("")
        self.threshold_spin.setValue(50)
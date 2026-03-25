from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt, QEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
)

from constants import ISSUE_TITLE_MAX_LENGTH, ISSUE_DESCRIPTION_MAX_LENGTH
from ui.models.issue_draft import IssueDraft


class FieldBlock(QWidget):
    def __init__(
        self,
        title: str,
        input_widget: QWidget,
        error_label: QLabel,
        counter_label: QLabel,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setObjectName("fieldBlock")

        self.label = QLabel(title)
        self.label.setObjectName("fieldLabel")

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(error_label, 1)
        meta_row.addWidget(counter_label, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)
        layout.addWidget(input_widget)
        layout.addLayout(meta_row)

class ButtonBlock(QWidget):
    def __init__(
        self,
        primary_button: QPushButton,
        secondary_button: QPushButton,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setObjectName("buttonBlock")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(primary_button)
        layout.addWidget(secondary_button)


class CreateIssueOverlay(QWidget):
    created = pyqtSignal(IssueDraft)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("createIssueOverlay")
        self.hide()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._apply_styles()

        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
            self.raise_()

        self._update_counters()
        self._validate_form()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.overlay = QWidget(self)
        self.overlay.setObjectName("overlay")

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(40, 40, 40, 40)
        overlay_layout.setSpacing(0)

        overlay_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)

        center_row.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self.card = QWidget(self.overlay)
        self.card.setObjectName("dialogCard")
        self.card.setFixedWidth(560)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(30, 30, 30, 28)
        card_layout.setSpacing(16)

        self.title_label = QLabel("Create New Issue Proposal")
        self.title_label.setObjectName("dialogTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g., Improve vote review flow")
        self.title_edit.textChanged.connect(self._on_title_changed)

        self.title_error_label = QLabel("")
        self.title_error_label.setObjectName("errorLabel")
        self.title_error_label.hide()

        self.title_counter_label = QLabel("")
        self.title_counter_label.setObjectName("counterLabel")
        self.title_counter_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Provide details about the issue, goals, and expected community impact..."
        )
        self.description_edit.setFixedHeight(140)
        self.description_edit.textChanged.connect(self._on_description_changed)

        self.description_error_label = QLabel("")
        self.description_error_label.setObjectName("errorLabel")
        self.description_error_label.hide()

        self.description_counter_label = QLabel("")
        self.description_counter_label.setObjectName("counterLabel")
        self.description_counter_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.title_block = FieldBlock(
            title="Issue Title",
            input_widget=self.title_edit,
            error_label=self.title_error_label,
            counter_label=self.title_counter_label,
            parent=self.card,
        )

        self.description_block = FieldBlock(
            title="Description",
            input_widget=self.description_edit,
            error_label=self.description_error_label,
            counter_label=self.description_counter_label,
            parent=self.card,
        )

        self.create_btn = QPushButton("Create Issue")
        self.create_btn.setObjectName("primaryButton")
        self.create_btn.clicked.connect(self._create)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.close_overlay)

        self.button_block = ButtonBlock(
            primary_button=self.create_btn,
            secondary_button=self.cancel_btn,
            parent=self.card,
        )

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.title_block)
        card_layout.addWidget(self.description_block)
        card_layout.addWidget(self.button_block)

        center_row.addWidget(self.card)

        center_row.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        overlay_layout.addLayout(center_row)

        overlay_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        root.addWidget(self.overlay)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#createIssueOverlay {
                background: transparent;
            }

            QWidget#overlay {
                background: rgba(0, 0, 0, 150);
            }

            QWidget#dialogCard {
                background: #1e2332;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 22px;
            }

            QLabel {
                color: #e5e7eb;
            }

            QLabel#dialogTitle {
                font-size: 24px;
                font-weight: 700;
                color: #f8fafc;
            }

            QLabel#fieldLabel {
                font-size: 14px;
                font-weight: 600;
                color: #f3f4f6;
            }

            QLabel#errorLabel {
                color: #fca5a5;
                font-size: 12px;
            }

            QLineEdit, QTextEdit {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 12px;
                color: #f8fafc;
                font-size: 14px;
                padding: 12px 14px;
            }

            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #8b5cf6;
            }

            QLineEdit[invalid="true"], QTextEdit[invalid="true"] {
                border: 1px solid #ef4444;
            }

            QTextEdit {
                padding-top: 12px;
            }

            QPushButton {
                border: none;
                border-radius: 12px;
                font-size: 15px;
                padding: 14px 18px;
                text-align: center;
            }

            QPushButton#primaryButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed,
                    stop:1 #6366f1
                );
                color: white;
                font-weight: 700;
            }

            QPushButton#primaryButton:hover:!disabled {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8b5cf6,
                    stop:1 #7c3aed
                );
            }

            QPushButton#primaryButton:disabled {
                background: rgba(255, 255, 255, 0.10);
                color: rgba(255, 255, 255, 0.45);
            }

            QPushButton#secondaryButton {
                background: transparent;
                color: #a1a1aa;
                font-weight: 500;
            }

            QPushButton#secondaryButton:hover {
                background: rgba(255, 255, 255, 0.04);
                color: #e5e7eb;
            }

            QLabel#counterLabel {
                color: #9ca3af;
                font-size: 12px;
                min-width: 70px;
            }

            QLabel#counterLabel[overLimit="true"] {
                color: #fca5a5;
                font-weight: 600;
            }
        """)

    def open_overlay(self) -> None:
        self._clear_fields()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.activateWindow()
        self.title_edit.setFocus()
        self._update_counters()
        self._validate_form()

    def close_overlay(self) -> None:
        self.hide()
        self.closed.emit()

    def _clear_fields(self) -> None:
        self.title_edit.clear()
        self.description_edit.clear()
        self._clear_errors()
        self._update_counters()

    def _clear_errors(self) -> None:
        self.title_error_label.clear()
        self.title_error_label.hide()

        self.description_error_label.clear()
        self.description_error_label.hide()

        self._set_field_invalid(self.title_edit, False)
        self._set_field_invalid(self.description_edit, False)

    def _set_field_invalid(self, widget: QWidget, invalid: bool) -> None:
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _current_draft(self) -> IssueDraft:
        return IssueDraft(
            title=self.title_edit.text(),
            description=self.description_edit.toPlainText(),
        ).normalized()

    def _validate_form(self) -> bool:
        draft = self._current_draft()
        errors = draft.validate()

        title_error = errors.get("title", "")
        description_error = errors.get("description", "")

        self.title_error_label.setText(title_error)
        self.title_error_label.setVisible(bool(title_error))

        self.description_error_label.setText(description_error)
        self.description_error_label.setVisible(bool(description_error))

        self._set_field_invalid(self.title_edit, bool(title_error))
        self._set_field_invalid(self.description_edit, bool(description_error))

        is_valid = not errors
        self.create_btn.setEnabled(is_valid)

        return is_valid

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_overlay()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)

    def _create(self) -> None:
        if not self._validate_form():
            return

        draft = self._current_draft()
        self.created.emit(draft)
        self.close_overlay()

    def _set_counter_over_limit(self, label: QLabel, over_limit: bool) -> None:
        label.setProperty("overLimit", over_limit)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _update_counters(self) -> None:
        title_length = len(self.title_edit.text())
        description_length = len(self.description_edit.toPlainText())

        self.title_counter_label.setText(f"{title_length}/{ISSUE_TITLE_MAX_LENGTH}")
        self.description_counter_label.setText(
            f"{description_length}/{ISSUE_DESCRIPTION_MAX_LENGTH}"
        )

        self._set_counter_over_limit(
            self.title_counter_label,
            title_length > ISSUE_TITLE_MAX_LENGTH,
        )
        self._set_counter_over_limit(
            self.description_counter_label,
            description_length > ISSUE_DESCRIPTION_MAX_LENGTH,
        )

    def _on_title_changed(self) -> None:
        self._update_counters()
        self._validate_form()

    def _on_description_changed(self) -> None:
        self._update_counters()
        self._validate_form()
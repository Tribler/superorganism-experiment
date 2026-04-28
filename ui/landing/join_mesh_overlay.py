from __future__ import annotations

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QFrame,
    QToolButton,
)


class CopyableValueCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setProperty("role", "payment-address-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        label = QLabel(title)
        label.setProperty("role", "payment-address-label")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "payment-address-value")
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value_label.setWordWrap(True)

        self.copy_btn = QPushButton()
        self.copy_btn.setProperty("variant", "icon-square")
        self.copy_btn.setFixedSize(40, 40)
        self.copy_btn.setIcon(icon("document-duplicate"))
        self.copy_btn.setIconSize(icon_size(18))
        self.copy_btn.clicked.connect(self.copy_value)

        row.addWidget(self.value_label, 1)
        row.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(label)
        layout.addLayout(row)

    def text(self) -> str:
        return self.value_label.text()

    def set_text(self, value: str) -> None:
        self.value_label.setText(value)

    def copy_value(self) -> None:
        QGuiApplication.clipboard().setText(self.text())


from ui.common.icons import icon, icon_size
from ui.constants import JOIN_MESH_EXPECTED_FEE_SATS


class JoinMeshOverlay(QWidget):
    create_account_requested = Signal(str)
    closed = Signal()

    def __init__(
        self,
        payment_address: str = "",
        expected_fee_sats: int = JOIN_MESH_EXPECTED_FEE_SATS,
        public_key: str = "",
        commitment: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._payment_address = payment_address
        self._expected_fee_sats = expected_fee_sats
        self._public_key = public_key
        self._commitment = commitment

        self.setObjectName("joinMeshOverlay")
        self.hide()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()

        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
            self.raise_()

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

        self.card = QFrame(self.overlay)
        self.card.setObjectName("joinMeshCard")
        self.card.setFixedWidth(660)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(34, 36, 34, 18)
        card_layout.setSpacing(22)

        top_icon_wrap = QFrame(self.card)
        top_icon_wrap.setProperty("role", "join-mesh-icon-wrap")
        top_icon_wrap.setFixedSize(48, 48)

        top_icon_layout = QVBoxLayout(top_icon_wrap)
        top_icon_layout.setContentsMargins(0, 0, 0, 0)
        top_icon_layout.setSpacing(0)

        self.top_icon_lbl = QToolButton()
        self.top_icon_lbl.setProperty("role", "join-mesh-icon")
        self.top_icon_lbl.setFixedSize(24, 24)
        self.top_icon_lbl.setIcon(icon("fingerprint"))
        self.top_icon_lbl.setIconSize(icon_size(24))
        self.top_icon_lbl.setAutoRaise(True)
        self.top_icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.top_icon_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        top_icon_layout.addWidget(self.top_icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        header_wrap = QWidget(self.card)
        header_layout = QVBoxLayout(header_wrap)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.title_label = QLabel("Create account")
        self.title_label.setProperty("role", "join-mesh-title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle_label = QLabel(
            "To create your account, please send the payment for your "
            "selected plan to the Bitcoin address below. Include the commitment "
            "in the OP_RETURN output and save your transaction ID for verification."
        )
        self.subtitle_label.setProperty("role", "join-mesh-subtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)

        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.address_card = CopyableValueCard(
            title="BITCOIN PAYMENT ADDRESS",
            value=self._payment_address,
            parent=self.card,
        )
        self.commitment_card = CopyableValueCard(
            title="TRANSACTION COMMITMENT",
            value=self._commitment,
            parent=self.card,
        )
        self.public_key_card = CopyableValueCard(
            title="PUBLIC KEY",
            value=self._public_key,
            parent=self.card,
        )

        txid_field_layout = QVBoxLayout()
        txid_field_layout.setContentsMargins(0, 0, 0, 0)
        txid_field_layout.setSpacing(8)

        txid_label = QLabel("Transaction ID (TXID)")
        txid_label.setProperty("role", "join-mesh-field-label")

        self.txid_edit = QLineEdit()
        self.txid_edit.setObjectName("joinMeshTxidInput")
        self.txid_edit.setProperty("variant", "join-mesh-input")
        self.txid_edit.setPlaceholderText("Transaction ID")

        txid_field_layout.addWidget(txid_label)
        txid_field_layout.addWidget(self.txid_edit)

        pills_row = QHBoxLayout()
        pills_row.setContentsMargins(0, 0, 0, 0)
        pills_row.setSpacing(12)

        min_conf_pill = QLabel("!  MIN. 3 CONFIRMATIONS REQUIRED")
        min_conf_pill.setProperty("role", "join-mesh-pill")
        min_conf_pill.setProperty("tone", "danger")

        verification_pill = QLabel("◔  AVG. VERIFICATION: 20 MINS")
        verification_pill.setProperty("role", "join-mesh-pill")
        verification_pill.setProperty("tone", "neutral")

        pills_row.addWidget(min_conf_pill, 0)
        pills_row.addWidget(verification_pill, 0)
        pills_row.addStretch()

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 10, 0, 0)
        actions_row.setSpacing(14)

        self.verify_btn = QPushButton("Verify Payment")
        self.verify_btn.setProperty("variant", "join-mesh-primary")
        self.verify_btn.setMinimumHeight(58)
        self.verify_btn.clicked.connect(self._emit_verify)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("variant", "join-mesh-secondary")
        self.cancel_btn.setMinimumHeight(58)
        self.cancel_btn.clicked.connect(self.close_overlay)

        actions_row.addWidget(self.verify_btn, 1)
        actions_row.addWidget(self.cancel_btn, 0)

        card_layout.addWidget(top_icon_wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        card_layout.addWidget(header_wrap)
        card_layout.addWidget(self.address_card)
        card_layout.addWidget(self.commitment_card)
        card_layout.addWidget(self.public_key_card)
        card_layout.addLayout(txid_field_layout)
        card_layout.addLayout(pills_row)
        card_layout.addLayout(actions_row)
        card_layout.addSpacing(10)

        center_row.addWidget(self.card)

        center_row.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        overlay_layout.addLayout(center_row)

        overlay_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        root.addWidget(self.overlay)

    def open_overlay(self) -> None:
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())

        self.show()
        self.raise_()
        self.activateWindow()
        self.txid_edit.setFocus()

    def close_overlay(self) -> None:
        self.hide()
        self.closed.emit()

    def set_payment_address(self, address: str) -> None:
        self._payment_address = address
        self.address_card.set_text(address)

    def set_public_key(self, public_key: str) -> None:
        self._public_key = public_key
        self.public_key_card.set_text(public_key)

    def set_commitment(self, commitment: str) -> None:
        self._commitment = commitment
        self.commitment_card.set_text(commitment)

    def _emit_verify(self) -> None:
        self.create_account_requested.emit(self.txid_edit.text().strip())

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
from __future__ import annotations

from PySide6.QtCore import Qt, QEvent, Signal
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

from ui.common.icons import icon, icon_size
from ui.landing.join_mesh_overlay import CopyableValueCard


class LoginOverlay(QWidget):
    public_key_committed = Signal(str)
    load_saved_login_requested = Signal(str)
    sign_now_requested = Signal()
    login_requested = Signal(str, str, str)
    closed = Signal()

    def __init__(
        self,
        commitment: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._commitment = commitment
        self._last_committed_public_key = ""

        self.setObjectName("loginOverlay")
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

        self.title_label = QLabel("Login")
        self.title_label.setProperty("role", "join-mesh-title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle_label = QLabel(
            "Sign in using your existing account credentials. "
            "Provide your public key below, then sign the commitment "
            "with your private key to verify ownership."
        )
        self.subtitle_label.setProperty("role", "join-mesh-subtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)

        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignHCenter)

        public_key_field_wrap = QWidget(self.card)
        public_key_field_layout = QVBoxLayout(public_key_field_wrap)
        public_key_field_layout.setContentsMargins(0, 0, 0, 0)
        public_key_field_layout.setSpacing(8)

        public_key_label = QLabel("Public Key Hex")
        public_key_label.setProperty("role", "join-mesh-field-label")

        public_key_row = QHBoxLayout()
        public_key_row.setContentsMargins(0, 0, 0, 0)
        public_key_row.setSpacing(12)

        self.public_key_edit = QLineEdit()
        self.public_key_edit.setObjectName("loginPublicKeyInput")
        self.public_key_edit.setProperty("variant", "join-mesh-input")
        self.public_key_edit.setPlaceholderText("Enter your public key hex")
        self.public_key_edit.editingFinished.connect(self._emit_public_key_committed_if_changed)

        self.load_saved_btn = QPushButton("Load Saved")
        self.load_saved_btn.setProperty("variant", "join-mesh-secondary")
        self.load_saved_btn.setMinimumHeight(48)
        self.load_saved_btn.clicked.connect(self._emit_load_saved_login)

        public_key_row.addWidget(self.public_key_edit, 1)
        public_key_row.addWidget(self.load_saved_btn, 0)

        public_key_field_layout.addWidget(public_key_label)
        public_key_field_layout.addLayout(public_key_row)

        txid_field_layout = QVBoxLayout()
        txid_field_layout.setContentsMargins(0, 0, 0, 0)
        txid_field_layout.setSpacing(8)

        txid_label = QLabel("Transaction ID (TXID)")
        txid_label.setProperty("role", "join-mesh-field-label")

        self.txid_edit = QLineEdit()
        self.txid_edit.setObjectName("loginTxidInput")
        self.txid_edit.setProperty("variant", "join-mesh-input")
        self.txid_edit.setPlaceholderText("Transaction ID")

        txid_field_layout.addWidget(txid_label)
        txid_field_layout.addWidget(self.txid_edit)

        private_key_field_layout = QVBoxLayout()
        private_key_field_layout.setContentsMargins(0, 0, 0, 0)
        private_key_field_layout.setSpacing(8)

        private_key_label = QLabel("Private Key Hex")
        private_key_label.setProperty("role", "join-mesh-field-label")

        self.private_key_edit = QLineEdit()
        self.private_key_edit.setObjectName("loginPrivateKeyInput")
        self.private_key_edit.setProperty("variant", "join-mesh-input")
        self.private_key_edit.setPlaceholderText("Enter your private key hex")

        private_key_field_layout.addWidget(private_key_label)
        private_key_field_layout.addWidget(self.private_key_edit)

        self.commitment_card = CopyableValueCard(
            title="LOGIN COMMITMENT TO SIGN",
            value=self._commitment,
            parent=self.card,
        )

        signature_field_wrap = QWidget(self.card)
        signature_field_layout = QVBoxLayout(signature_field_wrap)
        signature_field_layout.setContentsMargins(0, 0, 0, 0)
        signature_field_layout.setSpacing(8)

        signature_label = QLabel("Signature")
        signature_label.setProperty("role", "join-mesh-field-label")

        signature_row = QHBoxLayout()
        signature_row.setContentsMargins(0, 0, 0, 0)
        signature_row.setSpacing(12)

        self.signature_edit = QLineEdit()
        self.signature_edit.setObjectName("loginSignatureInput")
        self.signature_edit.setProperty("variant", "join-mesh-input")
        self.signature_edit.setPlaceholderText("Enter your signature")

        self.sign_now_btn = QPushButton("Sign Now")
        self.sign_now_btn.setProperty("variant", "join-mesh-secondary")
        self.sign_now_btn.setMinimumHeight(48)
        self.sign_now_btn.clicked.connect(self._emit_sign_now)

        signature_row.addWidget(self.signature_edit, 1)
        signature_row.addWidget(self.sign_now_btn, 0)

        signature_field_layout.addWidget(signature_label)
        signature_field_layout.addLayout(signature_row)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 10, 0, 0)
        actions_row.setSpacing(14)

        self.login_btn = QPushButton("Login")
        self.login_btn.setProperty("variant", "join-mesh-primary")
        self.login_btn.setMinimumHeight(58)
        self.login_btn.clicked.connect(self._emit_login)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("variant", "join-mesh-secondary")
        self.cancel_btn.setMinimumHeight(58)
        self.cancel_btn.clicked.connect(self.close_overlay)

        actions_row.addWidget(self.login_btn, 1)
        actions_row.addWidget(self.cancel_btn, 0)

        card_layout.addWidget(top_icon_wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        card_layout.addWidget(header_wrap)
        card_layout.addWidget(public_key_field_wrap)
        card_layout.addLayout(txid_field_layout)
        card_layout.addLayout(private_key_field_layout)
        card_layout.addWidget(self.commitment_card)
        card_layout.addWidget(signature_field_wrap)
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
        self.public_key_edit.setFocus()

    def close_overlay(self) -> None:
        self.hide()
        self.closed.emit()

    def set_commitment(self, commitment: str) -> None:
        self._commitment = commitment
        self.commitment_card.set_text(commitment)

    def public_key(self) -> str:
        return self.public_key_edit.text().strip()

    def private_key(self) -> str:
        return self.private_key_edit.text().strip()

    def set_public_key(self, public_key: str) -> None:
        self.public_key_edit.setText(public_key)

    def set_txid(self, txid: str) -> None:
        self.txid_edit.setText(txid)

    def set_private_key(self, private_key: str) -> None:
        self.private_key_edit.setText(private_key)

    def set_signature(self, signature: str) -> None:
        self.signature_edit.setText(signature)

    def set_credentials(self, public_key: str, txid: str, private_key: str) -> None:
        self.set_public_key(public_key)
        self.set_txid(txid)
        self.set_private_key(private_key)

    def clear_fields(self) -> None:
        self.public_key_edit.clear()
        self.txid_edit.clear()
        self.private_key_edit.clear()
        self.signature_edit.clear()

    def _emit_public_key_committed_if_changed(self) -> None:
        normalized_public_key = self.public_key()
        if normalized_public_key == self._last_committed_public_key:
            return

        self._last_committed_public_key = normalized_public_key
        self.public_key_committed.emit(normalized_public_key)

    def _emit_load_saved_login(self) -> None:
        self.load_saved_login_requested.emit(self.public_key())

    def _emit_sign_now(self) -> None:
        self.sign_now_requested.emit()

    def _emit_login(self) -> None:
        self.login_requested.emit(
            self.public_key_edit.text().strip(),
            self.txid_edit.text().strip(),
            self.signature_edit.text().strip(),
        )

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

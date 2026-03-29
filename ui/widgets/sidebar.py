from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)


class SidebarWidget(QFrame):
    torrents_clicked = pyqtSignal()
    fleet_clicked = pyqtSignal()
    issues_clicked = pyqtSignal()
    my_issues_clicked = pyqtSignal()
    voting_history_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    create_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setProperty("role", "sidebar")
        self.setFixedWidth(275)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 32, 16, 24)
        layout.setSpacing(0)

        brand_wrap = QWidget()
        brand_layout = QVBoxLayout(brand_wrap)
        brand_layout.setContentsMargins(16, 0, 16, 0)
        brand_layout.setSpacing(2)

        self.brand_title = QLabel("SuperOrganism")
        self.brand_title.setProperty("role", "sidebar-brand-title")

        self.brand_subtitle = QLabel("Attack-resilient Seedbox")
        self.brand_subtitle.setProperty("role", "sidebar-brand-subtitle")

        brand_layout.addWidget(self.brand_title)
        brand_layout.addWidget(self.brand_subtitle)

        nav_wrap = QWidget()
        nav_layout = QVBoxLayout(nav_wrap)
        nav_layout.setContentsMargins(0, 28, 0, 0)
        nav_layout.setSpacing(4)

        self.torrents_btn = QPushButton("Torrents")
        self.fleet_btn = QPushButton("Fleet")
        self.issues_btn = QPushButton("Issues")
        self.my_issues_btn = QPushButton("My Issues")
        self.voting_history_btn = QPushButton("Voting History")
        self.settings_btn = QPushButton("Settings")

        self._nav_buttons = (
            self.torrents_btn,
            self.fleet_btn,
            self.issues_btn,
            self.my_issues_btn,
            self.voting_history_btn,
            self.settings_btn,
        )

        for btn in self._nav_buttons:
            btn.setProperty("variant", "nav")
            btn.setProperty("active", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_layout.addWidget(btn)

        self.create_btn = QPushButton("Create New Issue")
        self.create_btn.setProperty("variant", "cta")
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        cta_wrap = QWidget()
        cta_layout = QVBoxLayout(cta_wrap)
        cta_layout.setContentsMargins(16, 0, 16, 0)
        cta_layout.setSpacing(0)
        cta_layout.addWidget(self.create_btn)

        self.user_wrap = QFrame()
        self.user_wrap.setProperty("role", "sidebar-user-wrap")

        user_layout = QHBoxLayout(self.user_wrap)
        user_layout.setContentsMargins(16, 16, 16, 0)
        user_layout.setSpacing(12)

        self.avatar_lbl = QLabel("AR")
        self.user_wrap.setProperty("role", "sidebar-user-wrap")
        self.avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_lbl.setFixedSize(40, 40)

        user_text_col = QVBoxLayout()
        user_text_col.setContentsMargins(0, 0, 0, 0)
        user_text_col.setSpacing(2)

        self.user_name_lbl = QLabel("Alex Rivera")
        self.user_name_lbl.setProperty("role", "sidebar-user-name")

        self.user_meta_lbl = QLabel("ID: 8821")
        self.user_meta_lbl.setProperty("role", "sidebar-user-meta")

        user_text_col.addWidget(self.user_name_lbl)
        user_text_col.addWidget(self.user_meta_lbl)

        user_layout.addWidget(self.avatar_lbl)
        user_layout.addLayout(user_text_col)

        layout.addWidget(brand_wrap)
        layout.addWidget(nav_wrap)
        layout.addStretch()
        layout.addWidget(cta_wrap)
        layout.addWidget(self.user_wrap)

        self.issues_btn.setProperty("active", True)
        self._refresh_nav_styles()

        self.torrents_btn.clicked.connect(self.torrents_clicked.emit)
        self.fleet_btn.clicked.connect(self.fleet_clicked.emit)
        self.issues_btn.clicked.connect(self.issues_clicked.emit)
        self.my_issues_btn.clicked.connect(self.my_issues_clicked.emit)
        self.voting_history_btn.clicked.connect(self.voting_history_clicked.emit)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        self.create_btn.clicked.connect(self.create_clicked.emit)

    def set_active_by_name(self, name: str) -> None:
        mapping = {
            "torrents": self.torrents_btn,
            "fleet": self.fleet_btn,
            "issues": self.issues_btn,
            "my_issues": self.my_issues_btn,
            "voting_history": self.voting_history_btn,
            "settings": self.settings_btn,
        }

        active_btn = mapping.get(name)
        if active_btn is None:
            return

        for btn in self._nav_buttons:
            btn.setProperty("active", btn is active_btn)

        self._refresh_nav_styles()

    def _refresh_nav_styles(self) -> None:
        for btn in self._nav_buttons:
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
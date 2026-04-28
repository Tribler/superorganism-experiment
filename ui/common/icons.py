from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from ui.resources import resources_rc  # noqa: F401 - registers compiled Qt resources


def icon(name: str) -> QIcon:
    return QIcon(f":/icons/{name}.svg")


def icon_size(px: int) -> QSize:
    return QSize(px, px)

from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from ui.resources import resources_rc  # noqa: F401 - registers compiled Qt resources


INTER_FONT_FAMILY = "Inter"

_APP_FONT_PATHS = (
    ":/fonts/inter/Inter-VariableFont_opsz,wght.ttf",
    ":/fonts/inter/Inter-Italic-VariableFont_opsz,wght.ttf",
)

_fonts_loaded = False


def load_application_fonts() -> None:
    global _fonts_loaded

    if _fonts_loaded:
        return

    for font_path in _APP_FONT_PATHS:
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id == -1:
            print(f"Failed to load application font: {font_path}")

    _fonts_loaded = True

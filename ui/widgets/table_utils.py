from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableView


def apply_shared_table_config(
    table: QTableView,
    *,
    sorting_enabled: bool = True,
    alternating_rows: bool = True,
    stretch_last_section: bool = False,
    selection_mode: QAbstractItemView.SelectionMode = QTableView.SelectionMode.SingleSelection,
    edit_triggers: QAbstractItemView.EditTrigger = QTableView.EditTrigger.NoEditTriggers,
    horizontal_scrollbar_policy: Qt.ScrollBarPolicy = Qt.ScrollBarPolicy.ScrollBarAsNeeded,
    vertical_scrollbar_policy: Qt.ScrollBarPolicy = Qt.ScrollBarPolicy.ScrollBarAsNeeded,
    focus_policy: Qt.FocusPolicy = Qt.FocusPolicy.StrongFocus,
) -> None:
    table.setSortingEnabled(sorting_enabled)
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection_mode)
    table.setShowGrid(False)
    table.setAlternatingRowColors(alternating_rows)
    table.setMouseTracking(True)
    table.setEditTriggers(edit_triggers)
    table.setFocusPolicy(focus_policy)
    table.setHorizontalScrollBarPolicy(horizontal_scrollbar_policy)
    table.setVerticalScrollBarPolicy(vertical_scrollbar_policy)

    table.verticalHeader().hide()

    header = table.horizontalHeader()
    header.setVisible(True)
    header.setHighlightSections(False)
    header.setSectionsClickable(True)
    header.setSectionsMovable(False)
    header.setStretchLastSection(stretch_last_section)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setMinimumSectionSize(44)
    header.setDefaultSectionSize(140)
    header.setFixedHeight(48)

    if sorting_enabled:
        header.setSortIndicatorShown(True)
    else:
        header.setSortIndicatorShown(False)
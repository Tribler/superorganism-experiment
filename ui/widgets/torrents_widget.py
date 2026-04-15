from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableView,
    QFrame,
    QHeaderView,
)

from ui.widgets.table_utils import apply_shared_table_config

COLUMNS = ["Infohash", "Seeders", "Leechers", "Total Peers", "Growth %", "Shrink %", "Exploding", "Status", "Last Check"]

COL_INFOHASH = 0
COL_SEEDERS = 1
COL_LEECHERS = 2
COL_TOTAL = 3
COL_GROWTH = 4
COL_SHRINK = 5
COL_EXPLODING = 6
COL_STATUS = 7
COL_LAST_CHECK = 8


class TorrentTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def load(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_INFOHASH:
                ih = row.get("infohash", "")
                return ih[:12] + "\u2026" if len(ih) > 12 else ih
            elif col == COL_SEEDERS:
                return str(row.get("seeders", 0))
            elif col == COL_LEECHERS:
                return str(row.get("leechers", 0))
            elif col == COL_TOTAL:
                return str(row.get("total_peers", 0))
            elif col == COL_GROWTH:
                return f"+{row.get('growth', 0.0):.1f}%"
            elif col == COL_SHRINK:
                return f"-{abs(row.get('shrink', 0.0)):.1f}%"
            elif col == COL_EXPLODING:
                return "Yes" if row.get("exploding_estimator", 0.0) > 0.5 else "No"
            elif col == COL_STATUS:
                return "Healthy" if row.get("total_peers", 0) > 0 else "No Peers"
            elif col == COL_LAST_CHECK:
                ts = row.get("timestamp", 0)
                if ts:
                    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                return "-"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STATUS:
                return QColor("#34d399") if row.get("total_peers", 0) > 0 else QColor("#94a3b8")
            if col == COL_EXPLODING:
                if row.get("exploding_estimator", 0.0) > 0.5:
                    return QColor("#fb923c")

        return None


class TorrentsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "torrents-page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        title = QLabel("Torrents")
        title.setProperty("role", "page-title")

        stats_bar = QHBoxLayout()
        stats_bar.setSpacing(24)

        self._total_lbl = QLabel("Total: 0")
        self._healthy_lbl = QLabel("Healthy: 0")
        self._no_peers_lbl = QLabel("No Peers: 0")
        self._exploding_lbl = QLabel("Exploding: 0")

        self._total_lbl.setProperty("variant", "badge")
        self._total_lbl.setProperty("tone", "neutral")

        self._healthy_lbl.setProperty("variant", "badge")
        self._healthy_lbl.setProperty("tone", "success")

        self._no_peers_lbl.setProperty("variant", "badge")
        self._no_peers_lbl.setProperty("tone", "muted")

        self._exploding_lbl.setProperty("variant", "badge")
        self._exploding_lbl.setProperty("tone", "warning")

        for lbl in (self._total_lbl, self._healthy_lbl, self._no_peers_lbl, self._exploding_lbl):
            stats_bar.addWidget(lbl)

        stats_bar.addStretch()

        table_card = QFrame()
        table_card.setProperty("variant", "card")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self._model = TorrentTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setProperty("variant", "data-table")
        self._table.setModel(self._proxy)

        apply_shared_table_config(self._table)

        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 115)
        self._table.setColumnWidth(8, 162)

        card_layout.addWidget(self._table)
        self._table.clicked.connect(self._on_cell_clicked)
        self._proxy.sort(COL_SEEDERS, Qt.SortOrder.DescendingOrder)

        layout.addWidget(title)
        layout.addLayout(stats_bar)
        layout.addWidget(table_card, 1)

    def _on_cell_clicked(self, index) -> None:
        source = self._proxy.mapToSource(index)
        row = self._model._rows[source.row()]
        col = source.column()
        if col == COL_INFOHASH:
            QApplication.clipboard().setText(row.get("infohash", ""))

    def load(self, rows: list[dict]) -> None:
        self._model.load(rows)

        total = len(rows)
        healthy = sum(1 for r in rows if r.get("total_peers", 0) > 0)
        no_peers = total - healthy
        exploding = sum(1 for r in rows if r.get("exploding_estimator", 0.0) > 0.5)

        self._total_lbl.setText(f"Total: {total}")
        self._healthy_lbl.setText(f"Healthy: {healthy}")
        self._no_peers_lbl.setText(f"No Peers: {no_peers}")
        self._exploding_lbl.setText(f"Exploding: {exploding}")
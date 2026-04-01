from __future__ import annotations

import datetime
from typing import Any

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
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

COLUMNS = ["Name", "IP", "Commit", "Uptime", "Disk", "BTC", "BTC Address", "Runway", "Region", "Last Seen"]


def _fmt_uptime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def _fmt_disk(used_bytes: int, total_bytes: int) -> str:
    used_gb = used_bytes / (1024 ** 3)
    total_gb = total_bytes / (1024 ** 3)
    return f"{used_gb:.1f}/{total_gb:.1f} GB"


def _fmt_last_seen(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class FleetTableModel(QAbstractTableModel):
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
            if col == 0:
                return row.get("friendly_name", "")
            elif col == 1:
                return row.get("public_ip", "")
            elif col == 2:
                commit = row.get("git_commit_hash", "")
                return commit[:8] if commit else ""
            elif col == 3:
                return _fmt_uptime(row.get("uptime_seconds", 0))
            elif col == 4:
                return _fmt_disk(row.get("disk_used_bytes", 0), row.get("disk_total_bytes", 0))
            elif col == 5:
                return f"{row.get('btc_balance_sat', 0)} sat"
            elif col == 6:
                addr = row.get("btc_address", "")
                return addr[:10] + "\u2026" if len(addr) > 10 else addr
            elif col == 7:
                return f"{row.get('vps_days_remaining', 0)}d"
            elif col == 8:
                return row.get("vps_provider_region", "")
            elif col == 9:
                ts = row.get("last_seen", 0)
                return _fmt_last_seen(ts) if ts else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 7:
                days = row.get("vps_days_remaining", 0)
                if days > 30:
                    return QColor("#34d399")
                elif days >= 7:
                    return QColor("#fbbf24")
                else:
                    return QColor("#ef4444")

        return None


class FleetWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "fleet-page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        header = QHBoxLayout()
        title = QLabel("Fleet")
        title.setProperty("role", "page-title")

        self._node_count_lbl = QLabel("Nodes: 0")
        self._node_count_lbl.setProperty("variant", "badge")
        self._node_count_lbl.setProperty("tone", "info")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._node_count_lbl)

        table_card = QFrame()
        table_card.setProperty("variant", "card")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self._model = FleetTableModel()
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
        hdr.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 115)
        self._table.setColumnWidth(9, 162)

        card_layout.addWidget(self._table)
        self._table.clicked.connect(self._on_cell_clicked)
        self._proxy.sort(7, Qt.SortOrder.DescendingOrder)

        stats_bar = QHBoxLayout()
        stats_bar.setSpacing(24)

        self._total_lbl = QLabel("Total: 0")
        self._safe_lbl = QLabel("Safe: 0")
        self._safeish_lbl = QLabel("Safe-ish: 0")
        self._dying_lbl = QLabel("Dying: 0")

        self._total_lbl.setProperty("variant", "badge")
        self._total_lbl.setProperty("tone", "neutral")

        self._safe_lbl.setProperty("variant", "badge")
        self._safe_lbl.setProperty("tone", "success")

        self._safeish_lbl.setProperty("variant", "badge")
        self._safeish_lbl.setProperty("tone", "warning")

        self._dying_lbl.setProperty("variant", "badge")
        self._dying_lbl.setProperty("tone", "danger")

        for lbl in (self._total_lbl, self._safe_lbl, self._safeish_lbl, self._dying_lbl):
            stats_bar.addWidget(lbl)

        stats_bar.addStretch()

        layout.addLayout(header)
        layout.addLayout(stats_bar)
        layout.addWidget(table_card, 1)

    def _on_cell_clicked(self, index) -> None:
        source = self._proxy.mapToSource(index)
        row = self._model._rows[source.row()]
        col = source.column()
        if col == 6:
            QApplication.clipboard().setText(row.get("btc_address", ""))

    def load(self, fleet: dict) -> None:
        rows = sorted(fleet.values(), key=lambda x: x.get("friendly_name", ""))
        self._model.load(rows)
        self._node_count_lbl.setText(f"Nodes: {len(rows)}")

        total = len(rows)
        safe = sum(1 for r in rows if r.get("vps_days_remaining", 0) > 60)
        safeish = sum(1 for r in rows if 30 <= r.get("vps_days_remaining", 0) <= 60)
        dying = sum(1 for r in rows if r.get("vps_days_remaining", 0) < 30)

        self._total_lbl.setText(f"Total: {total}")
        self._safe_lbl.setText(f"Safe: {safe}")
        self._safeish_lbl.setText(f"Safe-ish: {safeish}")
        self._dying_lbl.setText(f"Dying: {dying}")
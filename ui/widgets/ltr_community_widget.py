"""LTR Community Experiment Widget.

Displays the *local* peer's live experiment status when running the
Eternal AutoResearch across distributed IPv8 peers.  Each running
application instance shows its own arm-pull results; gossip rounds
synchronise statistics with other peers on the network.

Layout (top → bottom):
  1. Header: title + status badge
  2. Config card: Dataset / Algorithm / Metric / Rounds / Queries / Gossip / Hot-swap  + RUN
  3. Status bar: Round badge · Phase badge · Elapsed · network-peers badge · config summary
  4. Scrollable area:
       a. Mean Reward per Arm chart (Y: mean reward, X: gossip round)  ← primary chart
       b. Cumulative Reward vs Oracle chart
       c. Local arm leaderboard table
       d. Event log
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QCheckBox,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

_BENCH_DIR = (
    Path(__file__).parent.parent.parent
    / "crowdsourced_learn_to_rank"
    / "ltr-benchmarking"
)
if str(_BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCH_DIR))

_ARM_COLORS = [
    "#7c4dff", "#34d399", "#fbbf24", "#ef4444",
    "#60a5fa", "#f472b6", "#a3e635", "#fb923c",
]

_RECENT_WINDOW = 50


def _arm_color(name: str, known: dict[str, str]) -> str:
    if name not in known:
        known[name] = _ARM_COLORS[len(known) % len(_ARM_COLORS)]
    return known[name]


def _detect_local_datasets() -> list[str]:
    try:
        from datasets import detect_datasets
        found = detect_datasets(_BENCH_DIR / "data")
        return found if found else ["istella"]
    except Exception:
        return ["istella"]


def _detect_local_models(dataset_id: str | None = None) -> list[str]:
    """Scan the models directory for available arms (read metadata `name` field).

    If `dataset_id` is given, only files whose filename starts with
    `{dataset_id}_` are returned — this matches load_experiment_models'
    glob pattern so the dropdown stays in sync with what actually loads.
    """
    import json
    models_dir = _BENCH_DIR / "models"
    names: list[str] = []
    if not models_dir.exists():
        return names
    pattern = f"{dataset_id}_*.meta.json" if dataset_id else "*.meta.json"
    for meta_file in sorted(models_dir.glob(pattern)):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
        except Exception:
            continue
        name = meta.get("name")
        if name and name not in names:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

class _BaseChart(FigureCanvas):
    def __init__(self, bg: str = "#161616"):
        self._fig = Figure(figsize=(5, 2.8), facecolor=bg)
        super().__init__(self._fig)
        self._ax = self._fig.add_subplot(111)
        self._style(bg)

    def _style(self, bg: str = "#161616") -> None:
        ax = self._ax
        ax.set_facecolor(bg)
        ax.tick_params(colors="#adaaaa", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#2a2a2a")
        self._fig.tight_layout(pad=1.2)

    def _empty_text(self, msg: str = "No data yet") -> None:
        self._ax.text(
            0.5, 0.5, msg,
            transform=self._ax.transAxes,
            ha="center", va="center",
            color="#5a5a5a", fontsize=10,
        )
        self.draw()

    def _label(self, xlabel: str, ylabel: str, title: str) -> None:
        ax = self._ax
        ax.set_xlabel(xlabel, color="#adaaaa", fontsize=8)
        ax.set_ylabel(ylabel, color="#adaaaa", fontsize=8)
        ax.set_title(title, color="#ffffff", fontsize=9, pad=6)

    def _legend(self) -> None:
        self._ax.legend(
            fontsize=7, framealpha=0.15,
            labelcolor="#ffffff", facecolor="#1e1e1e", edgecolor="#2a2a2a",
        )

    def reset(self) -> None:
        self._ax.cla()
        self._style()
        self._empty_text()


class MeanRewardChart(_BaseChart):
    """Mean Reward per Arm vs Gossip Round — the primary chart."""

    def __init__(self):
        super().__init__()
        self._label("Gossip Round", "Mean Reward per Arm", "Mean Reward per Arm")
        self._empty_text()
        self._color_map: dict[str, str] = {}

    def update_data(self, history: list[dict], excluded: set[str], recent_only: bool = False) -> None:
        if not history:
            return
        if recent_only and len(history) > _RECENT_WINDOW:
            history = history[-_RECENT_WINDOW:]
        self._ax.cla()
        self._style()
        self._label("Gossip Round", "Mean Reward per Arm", "Mean Reward per Arm")

        if recent_only:
            x_vals = list(range(1, len(history) + 1))
        else:
            x_vals = [h["round"] for h in history]
        all_arms: set[str] = set()
        for h in history:
            all_arms.update(h.get("arm_mean_reward", {}).keys())

        for arm in sorted(all_arms):
            color = _arm_color(arm, self._color_map)
            rewards = [h.get("arm_mean_reward", {}).get(arm) for h in history]
            alpha = 0.3 if arm in excluded else 1.0
            ls = "--" if arm in excluded else "-"
            label = f"{arm} ✗" if arm in excluded else arm
            self._ax.plot(
                x_vals, rewards,
                color=color, alpha=alpha, linestyle=ls,
                linewidth=1.8, marker="o", markersize=4, label=label,
            )

        if recent_only:
            self._ax.set_xlim(1, _RECENT_WINDOW)
            step = max(1, _RECENT_WINDOW // 10)
            self._ax.set_xticks(list(range(1, _RECENT_WINDOW + 1, step)))
        elif x_vals:
            self._ax.set_xticks(x_vals)
        self._legend()
        self._fig.tight_layout(pad=1.2)
        self.draw()


class CumulativeRewardChart(_BaseChart):
    """Cumulative Reward vs Oracle."""

    def __init__(self):
        super().__init__()
        self._label("Round", "Cumulative Score@10", "Cumulative Reward vs Oracle")
        self._empty_text()

    def update_data(self, history: list[dict], recent_only: bool = False) -> None:
        if not history:
            return
        if recent_only and len(history) > _RECENT_WINDOW:
            history = history[-_RECENT_WINDOW:]
        self._ax.cla()
        self._style()
        self._label("Round", "Cumulative Score@10", "Cumulative Reward vs Oracle")

        if recent_only:
            x_vals = list(range(1, len(history) + 1))
        else:
            x_vals = [h["round"] for h in history]
        bandit = [h.get("cumulative_reward", 0) for h in history]
        oracle = [h.get("oracle_cumulative", 0) for h in history]

        self._ax.plot(
            x_vals, bandit, color="#34d399",
            linewidth=1.8, marker="o", markersize=4, label="Local bandit",
        )
        self._ax.plot(
            x_vals, oracle, color="#ef4444",
            linewidth=1.8, marker="o", markersize=4, linestyle="--", label="Oracle",
        )

        if recent_only:
            self._ax.set_xlim(1, _RECENT_WINDOW)
            step = max(1, _RECENT_WINDOW // 10)
            self._ax.set_xticks(list(range(1, _RECENT_WINDOW + 1, step)))
        elif x_vals:
            self._ax.set_xticks(x_vals)
        self._legend()
        self._fig.tight_layout(pad=1.2)
        self.draw()


# ---------------------------------------------------------------------------
# Local-peer arm leaderboard
# ---------------------------------------------------------------------------

class _LocalLeaderboard(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setProperty("variant", "data-table")
        self.setHorizontalHeaderLabels(["#", "Model", "Pulls", "Mean Reward"])
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 30)
        self.setColumnWidth(2, 70)
        self.setColumnWidth(3, 100)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

    def update_data(self, peer: dict) -> None:
        arms_data = sorted(
            peer.get("arms", {}).items(),
            key=lambda kv: -kv[1].get("reward", 0),
        )
        excluded_set = set(peer.get("excluded", []))
        self.setRowCount(len(arms_data))

        for i, (arm, info) in enumerate(arms_data):
            pulls = info.get("pulls", 0)
            reward = info.get("reward", 0.0)
            is_excluded = arm in excluded_set
            is_best = (i == 0 and not is_excluded)

            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(arm),
                QTableWidgetItem(str(pulls)),
                QTableWidgetItem(f"{reward:.4f}"),
            ]
            for item in items:
                item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                if is_excluded:
                    item.setForeground(QColor("#555555"))
                elif is_best:
                    item.setForeground(QColor("#fbbf24"))

            for col, item in enumerate(items):
                self.setItem(i, col, item)


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

class _EventLog(QPlainTextEdit):
    _KIND_PREFIX = {
        "exclusion": "[EXCL]",
        "gossip":    "[GOSS]",
        "round":     "[RUND]",
        "info":      "[INFO]",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "ltr-log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(400)
        self.setFixedHeight(150)

    def append_event(self, entry: dict) -> None:
        t = entry.get("t", 0.0)
        kind = entry.get("kind", "info")
        msg = entry.get("msg", "")
        prefix = self._KIND_PREFIX.get(kind, "[INFO]")
        self.appendPlainText(f"[{t:7.1f}s] {prefix} {msg}")


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class LTRCommunityWidget(QWidget):
    """Eternal AutoResearch — distributed experiment widget.

    Each app instance is one IPv8 peer.  Results shown are *this* peer's
    local arm statistics after each gossip round.
    """

    run_requested = Signal(str, str, str, int, bool, int, str)
    # dataset, algorithm, metric, queries_per_tick, gossip, hotswap_tick, hotswap_model
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "ltr-page")
        self._last_snapshot: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 20)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Eternal AutoResearch")
        title.setProperty("role", "page-title")
        self._status_lbl = QLabel("Idle")
        self._status_lbl.setProperty("variant", "badge")
        self._status_lbl.setProperty("tone", "neutral")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._status_lbl)
        root.addLayout(header)

        # ── Subtitle / description ───────────────────────────────────────
        sub = QLabel(
            "This peer joins the IPv8 LTR community and runs the bandit "
            "experiment cooperatively with other peers on the network."
        )
        sub.setProperty("role", "ltr-subtitle")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # ── Config card ──────────────────────────────────────────────────
        cfg_card = QFrame()
        cfg_card.setProperty("variant", "card")
        cfg_outer = QVBoxLayout(cfg_card)
        cfg_outer.setContentsMargins(20, 16, 20, 16)
        cfg_outer.setSpacing(12)

        cfg_grid = QGridLayout()
        cfg_grid.setContentsMargins(0, 0, 0, 0)
        cfg_grid.setHorizontalSpacing(18)
        cfg_grid.setVerticalSpacing(6)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setProperty("role", "ltr-control-label")
            return l

        self._dataset_combo = QComboBox()
        self._dataset_combo.setProperty("variant", "default")
        self._dataset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for ds in _detect_local_datasets():
            self._dataset_combo.addItem(ds)

        self._algorithm_combo = QComboBox()
        self._algorithm_combo.setProperty("variant", "default")
        self._algorithm_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._algorithm_combo.addItems(["ucb1", "thompson"])

        self._metric_combo = QComboBox()
        self._metric_combo.setProperty("variant", "default")
        self._metric_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._metric_combo.addItems(["ndcg", "mrr"])

        self._queries_spin = QSpinBox()
        self._queries_spin.setProperty("variant", "default")
        self._queries_spin.setRange(10, 10000)
        self._queries_spin.setSingleStep(10)
        self._queries_spin.setValue(100)
        self._queries_spin.setToolTip(
            "Tick size: number of queries processed between each "
            "gossip + exclusion check."
        )

        self._gossip_check = QCheckBox("Gossip")
        self._gossip_check.setChecked(True)
        self._gossip_check.setProperty("role", "ltr-control-label")

        self._recent_only_check = QCheckBox(f"Display only last {_RECENT_WINDOW} ticks")
        self._recent_only_check.setChecked(True)
        self._recent_only_check.setProperty("role", "ltr-control-label")
        self._recent_only_check.setToolTip(
            "Show only the most recent ticks on the charts. "
            "Can be toggled live while the experiment is running."
        )
        self._recent_only_check.toggled.connect(self._on_recent_only_toggled)

        self._hotswap_spin = QSpinBox()
        self._hotswap_spin.setProperty("variant", "default")
        self._hotswap_spin.setRange(0, 50)
        self._hotswap_spin.setValue(0)
        self._hotswap_spin.setToolTip(
            "0 = disabled. Selected model is proposed at this tick."
        )

        self._hotswap_model_combo = QComboBox()
        self._hotswap_model_combo.setProperty("variant", "default")
        self._hotswap_model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hotswap_model_combo.setToolTip(
            "Model to propose at the hot-swap tick. Populated from the "
            "ltr-benchmarking/models folder — filtered to the selected dataset."
        )
        self._repopulate_hotswap_models(self._dataset_combo.currentText())
        self._dataset_combo.currentTextChanged.connect(self._repopulate_hotswap_models)

        self._run_btn = QPushButton("RUN")
        self._run_btn.setProperty("variant", "primary")
        self._run_btn.setFixedWidth(140)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.clicked.connect(self._on_run_clicked)

        self._stop_btn = QPushButton("STOP")
        self._stop_btn.setProperty("variant", "secondary")
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)

        # Three-column grid: label/widget pairs
        fields = [
            ("Dataset",        self._dataset_combo),
            ("Algorithm",      self._algorithm_combo),
            ("Metric",         self._metric_combo),
            ("Queries/tick",   self._queries_spin),
            ("Hot-swap tick",  self._hotswap_spin),
            ("Hot-swap model", self._hotswap_model_combo),
        ]
        cols_per_row = 3
        for idx, (label, widget) in enumerate(fields):
            row = (idx // cols_per_row) * 2
            col = idx % cols_per_row
            cfg_grid.addWidget(_lbl(label), row, col)
            cfg_grid.addWidget(widget, row + 1, col)

        cfg_outer.addLayout(cfg_grid)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(14)
        actions_row.addWidget(self._gossip_check)
        actions_row.addWidget(self._recent_only_check)
        actions_row.addStretch()
        actions_row.addWidget(self._stop_btn)
        actions_row.addWidget(self._run_btn)
        cfg_outer.addLayout(actions_row)

        root.addWidget(cfg_card)

        # ── Status bar ───────────────────────────────────────────────────
        status_bar = QHBoxLayout()
        status_bar.setSpacing(12)

        self._round_lbl   = QLabel("Round: —")
        self._phase_lbl   = QLabel("Phase: —")
        self._elapsed_lbl = QLabel("Elapsed: —")
        self._peers_lbl   = QLabel("Network peers: —")
        self._config_lbl  = QLabel("")

        for lbl in (self._round_lbl, self._phase_lbl, self._elapsed_lbl, self._peers_lbl):
            lbl.setProperty("variant", "badge")
            lbl.setProperty("tone", "neutral")
            status_bar.addWidget(lbl)

        self._config_lbl.setProperty("role", "ltr-control-label")
        status_bar.addWidget(self._config_lbl)
        status_bar.addStretch()
        root.addLayout(status_bar)

        # ── Scrollable main content ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(14)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        # ── Charts row ───────────────────────────────────────────────────
        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)

        def _chart_card(chart_widget: QWidget, title_text: str) -> QFrame:
            card = QFrame()
            card.setProperty("variant", "card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            t = QLabel(title_text)
            t.setProperty("role", "ltr-card-title")
            t.setContentsMargins(12, 8, 12, 4)
            cl.addWidget(t)
            cl.addWidget(chart_widget, 1)
            return card

        self._mean_reward_chart = MeanRewardChart()
        self._cumulative_chart  = CumulativeRewardChart()

        charts_row.addWidget(
            _chart_card(self._mean_reward_chart, "Mean Reward per Arm"), 1
        )
        charts_row.addWidget(
            _chart_card(self._cumulative_chart, "Cumulative Reward vs Oracle"), 1
        )
        scroll_layout.addLayout(charts_row)

        # ── Local leaderboard ────────────────────────────────────────────
        lb_card = QFrame()
        lb_card.setProperty("variant", "card")
        lb_layout = QVBoxLayout(lb_card)
        lb_layout.setContentsMargins(0, 0, 0, 0)
        lb_layout.setSpacing(0)
        lb_title = QLabel("Local Arm Leaderboard")
        lb_title.setProperty("role", "ltr-card-title")
        lb_title.setContentsMargins(14, 10, 14, 6)
        self._leaderboard = _LocalLeaderboard()
        lb_layout.addWidget(lb_title)
        lb_layout.addWidget(self._leaderboard)
        scroll_layout.addWidget(lb_card)

        # ── Event log ────────────────────────────────────────────────────
        log_card = QFrame()
        log_card.setProperty("variant", "card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        log_title = QLabel("Event Log")
        log_title.setProperty("role", "ltr-card-title")
        log_title.setContentsMargins(14, 10, 14, 4)
        self._event_log = _EventLog()
        log_layout.addWidget(log_title)
        log_layout.addWidget(self._event_log)
        scroll_layout.addWidget(log_card)

    # ------------------------------------------------------------------
    # Slots called by LTRCommunityThread
    # ------------------------------------------------------------------

    def on_started(self) -> None:
        self._set_status("Running", "warning")
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Running…")
        self._stop_btn.setEnabled(True)
        self._mean_reward_chart.reset()
        self._cumulative_chart.reset()
        self._leaderboard.setRowCount(0)
        self._event_log.clear()

    def on_snapshot(self, snap: dict) -> None:
        self._last_snapshot = snap
        round_num = snap.get("round", 0)
        phase     = snap.get("phase", "")
        elapsed   = snap.get("elapsed", 0.0)
        config    = snap.get("config", {})
        oracle    = snap.get("oracle", {})
        peer      = snap.get("peer", {})
        history   = snap.get("round_history", [])
        net_peers = snap.get("network_peers", 0)
        metric    = config.get("metric", "ndcg")
        recent_only = self._recent_only_check.isChecked()

        self._round_lbl.setText(f"Tick: {round_num}")
        self._phase_lbl.setText(f"Phase: {phase}")
        self._elapsed_lbl.setText(f"{elapsed:.0f}s")
        self._peers_lbl.setText(f"Network peers: {net_peers}")
        self._badge_tone(self._phase_lbl, phase)

        if config.get("dataset"):
            self._config_lbl.setText(
                f"{config['dataset']} · "
                f"{config.get('algorithm','').upper()} · "
                f"{config.get('metric','').upper()} · "
                f"{config.get('queries_per_round','')} q/tick"
            )

        excluded = set(peer.get("excluded", []))

        if history:
            self._mean_reward_chart.update_data(history, excluded, recent_only=recent_only)
            self._cumulative_chart.update_data(history, recent_only=recent_only)

        if peer:
            self._leaderboard.update_data(peer)

    def on_log_event(self, entry: dict) -> None:
        self._event_log.append_event(entry)

    def on_finished(self) -> None:
        self._set_status("Stopped", "success")
        self._run_btn.setEnabled(True)
        self._run_btn.setText("RUN")
        self._stop_btn.setEnabled(False)
        self._event_log.append_event(
            {"t": 0, "kind": "round", "msg": "── Experiment stopped ──"}
        )

    def on_error(self, msg: str) -> None:
        self._set_status("Error", "danger")
        self._run_btn.setEnabled(True)
        self._run_btn.setText("RUN")
        self._stop_btn.setEnabled(False)
        self._event_log.append_event(
            {"t": 0, "kind": "exclusion", "msg": f"ERROR: {msg}"}
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repopulate_hotswap_models(self, dataset_id: str) -> None:
        prev = self._hotswap_model_combo.currentText()
        self._hotswap_model_combo.blockSignals(True)
        self._hotswap_model_combo.clear()
        names = _detect_local_models(dataset_id)
        if not names:
            self._hotswap_model_combo.addItem("(none found)")
            self._hotswap_model_combo.setEnabled(False)
        else:
            self._hotswap_model_combo.setEnabled(True)
            for name in names:
                self._hotswap_model_combo.addItem(name)
            if prev in names:
                self._hotswap_model_combo.setCurrentText(prev)
        self._hotswap_model_combo.blockSignals(False)

    def _on_recent_only_toggled(self, _checked: bool) -> None:
        if self._last_snapshot is None:
            return
        history = self._last_snapshot.get("round_history", [])
        if not history:
            return
        recent_only = self._recent_only_check.isChecked()
        excluded = set(self._last_snapshot.get("peer", {}).get("excluded", []))
        self._mean_reward_chart.update_data(history, excluded, recent_only=recent_only)
        self._cumulative_chart.update_data(history, recent_only=recent_only)

    def _on_stop_clicked(self) -> None:
        self._stop_btn.setEnabled(False)
        self._set_status("Stopping", "warning")
        self._run_btn.setText("Stopping…")
        self.stop_requested.emit()

    def _on_run_clicked(self) -> None:
        self._last_snapshot = None
        self._mean_reward_chart.reset()
        self._cumulative_chart.reset()
        self._leaderboard.setRowCount(0)
        self._event_log.clear()
        self._round_lbl.setText("Tick: 0")
        self._phase_lbl.setText("Phase: starting")
        self._elapsed_lbl.setText("0s")
        self._peers_lbl.setText("Network peers: 0")
        self._set_status("Starting", "warning")
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Running…")
        hotswap_model = (
            self._hotswap_model_combo.currentText()
            if self._hotswap_model_combo.isEnabled()
            else ""
        )
        self.run_requested.emit(
            self._dataset_combo.currentText(),
            self._algorithm_combo.currentText(),
            self._metric_combo.currentText(),
            self._queries_spin.value(),
            self._gossip_check.isChecked(),
            self._hotswap_spin.value(),
            hotswap_model,
        )

    def _set_status(self, text: str, tone: str) -> None:
        self._status_lbl.setText(text)
        self._status_lbl.setProperty("tone", tone)
        self._status_lbl.style().unpolish(self._status_lbl)
        self._status_lbl.style().polish(self._status_lbl)
        self._status_lbl.update()

    def _badge_tone(self, lbl: QLabel, phase: str) -> None:
        tone_map = {
            "querying": "warning",
            "gossiping": "info",
            "survival": "danger",
            "finished": "success",
            "loading": "neutral",
            "idle": "neutral",
        }
        tone = tone_map.get(phase, "neutral")
        lbl.setProperty("tone", tone)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
        lbl.update()

"""Main window and tabs for NetTracker."""

import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import autostart, export, sources
from .nethogs import (
    NethogsMonitor,
    grant_capabilities,
    has_capabilities,
    nethogs_path,
)
from .settings import Settings
from .usagedb import UsageDB
from .utils import human_bytes, human_gb, human_rate, set_rate_unit
from .widgets import RX_COLOR, TX_COLOR, BarChart, CapBar, LiveGraph, make_icon

CAP_THRESHOLDS = (80, 100)
TRACK_INTERVAL = 2  # seconds between nethogs samples (also the integration dt)

STYLE = """
QMainWindow, QWidget { background: #0d1117; color: #e6edf3; }
QTabWidget::pane { border: 1px solid #222b36; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background: #161b22; color: #9aa4b2; padding: 8px 18px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #1f6feb; color: white; }
QTabBar::tab:hover:!selected { background: #1f2630; }
QComboBox {
    background: #161b22; border: 1px solid #2a3340; border-radius: 6px;
    padding: 5px 10px; min-width: 130px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #161b22; selection-background-color: #1f6feb;
    border: 1px solid #2a3340;
}
QPushButton {
    background: #21262d; border: 1px solid #2a3340; border-radius: 6px;
    padding: 7px 16px; color: #e6edf3;
}
QPushButton:hover { background: #2a313a; }
QPushButton:disabled { color: #565f6b; background: #161b22; }
QPushButton#accent { background: #1f6feb; border: none; }
QPushButton#accent:hover { background: #388bfd; }
QLabel#h1 { font-size: 22px; font-weight: 600; }
QLabel#muted { color: #9aa4b2; }
QFrame#card { background: #161b22; border: 1px solid #222b36; border-radius: 10px; }
QTableWidget {
    background: #11151c; gridline-color: #222b36; border: 1px solid #222b36;
    border-radius: 8px;
}
QHeaderView::section {
    background: #161b22; color: #9aa4b2; padding: 6px; border: none;
    border-bottom: 1px solid #222b36;
}
QTableWidget::item:selected { background: #1f6feb; }
QMenuBar { background: #0d1117; color: #e6edf3; }
QMenuBar::item:selected { background: #1f2630; }
QMenu { background: #161b22; color: #e6edf3; border: 1px solid #2a3340; }
QMenu::item:selected { background: #1f6feb; }
QDialog { background: #0d1117; }
QSpinBox, QDoubleSpinBox {
    background: #161b22; border: 1px solid #2a3340; border-radius: 6px;
    padding: 4px 8px; color: #e6edf3;
}
"""


def _card(*widgets, spacing=2):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    return frame


class StatCard(QFrame):
    """A small card showing a title and a big value, with an accent dot."""

    def __init__(self, title, color=None):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        head = QLabel(title)
        head.setObjectName("muted")
        if color:
            head.setText(f"<span style='color:{color.name()}'>●</span> {title}")
        self.value = QLabel("—")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        self.value.setFont(f)
        lay.addWidget(head)
        lay.addWidget(self.value)

    def set_value(self, text):
        self.value.setText(text)


class LiveTab(QWidget):
    speed_updated = pyqtSignal(float, float)  # rx_rate, tx_rate (bytes/s)

    def __init__(self):
        super().__init__()
        self.iface = None
        self.prev = None  # (rx, tx, monotonic_time)
        self.session_start = None  # (rx, tx)
        self.session_rx = 0
        self.session_tx = 0
        self.last_rx_rate = 0.0
        self.last_tx_rate = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        title = QLabel("Live Traffic")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel("Interface:"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_iface_changed)
        top.addWidget(self.combo)
        root.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_down = StatCard("Download", RX_COLOR)
        self.card_up = StatCard("Upload", TX_COLOR)
        self.card_sess = StatCard("Session total")
        for c in (self.card_down, self.card_up, self.card_sess):
            cards.addWidget(c)
        root.addLayout(cards)

        self.graph = LiveGraph()
        root.addWidget(_card(self.graph), stretch=1)

        legend = QLabel(
            f"<span style='color:{RX_COLOR.name()}'>■</span> Download&nbsp;&nbsp;"
            f"<span style='color:{TX_COLOR.name()}'>■</span> Upload"
        )
        legend.setObjectName("muted")
        root.addWidget(legend, alignment=Qt.AlignRight)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def populate(self, interfaces):
        self.combo.blockSignals(True)
        self.combo.clear()
        for info in interfaces:
            suffix = "" if info["is_up"] else f"  ({info['state']})"
            self.combo.addItem(info["name"] + suffix, info["name"])
        self.combo.blockSignals(False)

    def select_interface(self, name):
        idx = self.combo.findData(name) if name else -1
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_iface_changed(self.combo.currentIndex())

    def _on_iface_changed(self, _index):
        self.iface = self.combo.currentData()
        self.prev = None
        self.session_rx = 0
        self.session_tx = 0
        self.session_start = sources.read_counters(self.iface) if self.iface else None
        self.graph.clear()

    def refresh_units(self):
        self.card_down.set_value(human_rate(self.last_rx_rate))
        self.card_up.set_value(human_rate(self.last_tx_rate))
        self.graph.update()

    def start(self):
        self._tick()
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def _tick(self):
        if not self.iface:
            return
        rx, tx = sources.read_counters(self.iface)
        if rx is None:
            return
        now = time.monotonic()
        if self.prev is not None:
            dt = now - self.prev[2]
            if dt > 0:
                self.last_rx_rate = max(0, (rx - self.prev[0]) / dt)
                self.last_tx_rate = max(0, (tx - self.prev[1]) / dt)
                self.graph.add_sample(self.last_rx_rate, self.last_tx_rate)
                self.card_down.set_value(human_rate(self.last_rx_rate))
                self.card_up.set_value(human_rate(self.last_tx_rate))
                self.speed_updated.emit(self.last_rx_rate, self.last_tx_rate)
        if self.session_start is not None:
            self.session_rx = max(0, rx - self.session_start[0])
            self.session_tx = max(0, tx - self.session_start[1])
            self.card_sess.set_value(human_bytes(self.session_rx + self.session_tx))
        self.prev = (rx, tx, now)


class HistoryTab(QWidget):
    cap_changed = pyqtSignal(object)  # dict or None
    day_total_changed = pyqtSignal(float)  # today's total bytes

    def __init__(self, settings):
        super().__init__()
        self.iface = None
        self.settings = settings
        self._days = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        title = QLabel("Usage History")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        self.export_btn = QPushButton("Export CSV…")
        self.export_btn.clicked.connect(self._export_csv)
        top.addWidget(self.export_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_today = StatCard("Today")
        self.card_month = StatCard("This month")
        self.card_total = StatCard("All time")
        for c in (self.card_today, self.card_month, self.card_total):
            cards.addWidget(c)
        root.addLayout(cards)

        # Data-cap row
        self.cap_box = QFrame()
        self.cap_box.setObjectName("card")
        cap_lay = QVBoxLayout(self.cap_box)
        cap_lay.setContentsMargins(16, 12, 16, 12)
        self.cap_title = QLabel("Monthly data cap")
        self.cap_title.setObjectName("muted")
        self.cap_bar = CapBar()
        self.cap_forecast = QLabel("")
        self.cap_forecast.setObjectName("muted")
        cap_lay.addWidget(self.cap_title)
        cap_lay.addWidget(self.cap_bar)
        cap_lay.addWidget(self.cap_forecast)
        root.addWidget(self.cap_box)

        self.daily_label = QLabel("Last days")
        self.daily_label.setObjectName("muted")
        root.addWidget(self.daily_label)
        self.daily_chart = BarChart()
        root.addWidget(self.daily_chart, stretch=1)

        self.monthly_label = QLabel("Last months")
        self.monthly_label.setObjectName("muted")
        root.addWidget(self.monthly_label)
        self.monthly_chart = BarChart()
        root.addWidget(self.monthly_chart, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

    def set_iface(self, iface):
        self.iface = iface
        self.reload()

    def reload(self):
        if not self.iface:
            return
        if not sources.vnstat_available():
            self.status.setText("vnstat is not installed.")
            return
        try:
            entry = sources.fetch_vnstat(self.iface)
            hist = sources.parse_history(entry)
        except sources.VnstatError as exc:
            self.status.setText(f"vnstat: {exc}")
            return

        def fmt(row):
            if not row:
                return "—"
            return (
                f"{human_bytes(row['total'])}"
                f"   ↓{human_bytes(row['rx'])}  ↑{human_bytes(row['tx'])}"
            )

        self.card_today.set_value(fmt(hist["today"]))
        self.card_month.set_value(fmt(hist["this_month"]))
        self.card_total.set_value(fmt(hist["total"]))
        self.daily_chart.set_items(hist["days"][-14:])
        self.monthly_chart.set_items(hist["months"][-12:])
        self.daily_label.setText(f"Last days  ·  {hist['name']}")
        self.status.setText("Stacked bars: download (blue) + upload (green).")
        self._days = hist["days"]
        self._months = hist["months"]
        today_total = hist["today"]["total"] if hist["today"] else 0
        self.day_total_changed.emit(float(today_total))
        self._update_cap(hist["days"])

    def _update_cap(self, days):
        if not self.settings.get("cap_enabled"):
            self.cap_box.hide()
            self.cap_changed.emit(None)
            return
        limit_gb = float(self.settings.get("cap_limit_gb"))
        billing_day = int(self.settings.get("cap_billing_day"))
        used, start = sources.cycle_usage(days, billing_day)
        limit_bytes = limit_gb * 1_000_000_000.0
        fraction = used / limit_bytes if limit_bytes > 0 else 0.0
        caption = f"{human_gb(used)} of {limit_gb:g} GB  ·  {fraction * 100:.0f}%"
        self.cap_bar.set_progress(fraction, caption)
        self.cap_title.setText(f"Monthly data cap  ·  cycle since {start.isoformat()}")
        self.cap_forecast.setText(
            self._forecast_text(used, limit_bytes, start, limit_gb)
        )
        self.cap_box.show()
        self.cap_changed.emit(
            {
                "fraction": fraction,
                "used": used,
                "limit_gb": limit_gb,
                "cycle_key": start.isoformat(),
            }
        )

    def _forecast_text(self, used, limit_bytes, start, limit_gb):
        fc = sources.forecast(used, limit_bytes, start)
        proj = fc["projected_total"]
        end = fc["cycle_end"].strftime("%b %d")
        if used >= limit_bytes:
            return f"⚠ Cap exceeded — projected ~{human_gb(proj)} by {end}."
        if fc["hit_date"] is not None:
            hit = fc["hit_date"].strftime("%b %d")
            return (
                f"On pace to hit your {limit_gb:g} GB cap on {hit} "
                f"(~{human_gb(proj)} projected by {end})."
            )
        return (
            f"On track: ~{human_gb(proj)} projected by {end} "
            f"(under your {limit_gb:g} GB cap)."
        )

    def _export_csv(self):
        if not self._days:
            self.status.setText("Nothing to export yet — refresh first.")
            return
        default = f"nettracker-history-{self.iface or 'iface'}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export daily history", default, "CSV files (*.csv)"
        )
        if not path:
            return
        rows = [
            [d["label"], int(d["rx"]), int(d["tx"]), int(d["total"])]
            for d in self._days
        ]
        try:
            export.write_csv(
                path, ["date", "rx_bytes", "tx_bytes", "total_bytes"], rows
            )
            self.status.setText(f"Exported {len(rows)} days to {path}")
        except OSError as exc:
            self.status.setText(f"Export failed: {exc}")


class CapDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Data cap & alerts")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(430)

        form = QFormLayout(self)

        cap_head = QLabel("Monthly cap")
        cap_head.setObjectName("muted")
        form.addRow(cap_head)
        self.enable = QCheckBox("Enable monthly cap")
        self.enable.setChecked(bool(settings.get("cap_enabled")))
        form.addRow(self.enable)

        self.limit = QDoubleSpinBox()
        self.limit.setRange(0.1, 1_000_000.0)
        self.limit.setDecimals(1)
        self.limit.setSuffix(" GB")
        self.limit.setValue(float(settings.get("cap_limit_gb")))
        form.addRow("Limit:", self.limit)

        self.day = QSpinBox()
        self.day.setRange(1, 28)
        self.day.setValue(int(settings.get("cap_billing_day")))
        form.addRow("Billing day:", self.day)

        alert_head = QLabel("Usage alerts")
        alert_head.setObjectName("muted")
        form.addRow(QLabel(""))
        form.addRow(alert_head)

        self.daily_enable = QCheckBox("Alert when today's total exceeds")
        self.daily_enable.setChecked(bool(settings.get("daily_alert_enabled")))
        self.daily_gb = QDoubleSpinBox()
        self.daily_gb.setRange(0.1, 100_000.0)
        self.daily_gb.setDecimals(1)
        self.daily_gb.setSuffix(" GB")
        self.daily_gb.setValue(float(settings.get("daily_alert_gb")))
        form.addRow(self._alert_row(self.daily_enable, self.daily_gb))

        self.app_enable = QCheckBox("Alert when any app today exceeds")
        self.app_enable.setChecked(bool(settings.get("app_alert_enabled")))
        self.app_gb = QDoubleSpinBox()
        self.app_gb.setRange(0.1, 100_000.0)
        self.app_gb.setDecimals(1)
        self.app_gb.setSuffix(" GB")
        self.app_gb.setValue(float(settings.get("app_alert_gb")))
        form.addRow(self._alert_row(self.app_enable, self.app_gb))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _alert_row(checkbox, spin):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        spin.setMaximumWidth(120)
        lay.addWidget(checkbox, stretch=1)
        lay.addWidget(spin)
        return box

    def apply(self):
        s = self.settings
        s.set("cap_enabled", self.enable.isChecked(), save=False)
        s.set("cap_limit_gb", self.limit.value(), save=False)
        s.set("cap_billing_day", self.day.value(), save=False)
        s.set("daily_alert_enabled", self.daily_enable.isChecked(), save=False)
        s.set("daily_alert_gb", self.daily_gb.value(), save=False)
        s.set("app_alert_enabled", self.app_enable.isChecked(), save=False)
        s.set("app_alert_gb", self.app_gb.value(), save=False)
        # changing thresholds resets which notifications have fired
        s.set("cap_notified", {}, save=False)
        s.set("daily_notified", {}, save=False)
        s.set("app_notified", {}, save=False)
        s.save()


def _cell(text, color=None, align=Qt.AlignLeft | Qt.AlignVCenter):
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align)
    if color:
        item.setForeground(color)
    return item


class ProcessTab(QWidget):
    """Live per-process rates — a view onto the shared background monitor."""

    access_granted = pyqtSignal()
    tracking_toggled = pyqtSignal(bool)  # True = resume, False = pause

    def __init__(self):
        super().__init__()
        self._tracking = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Live Processes")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._toggle)
        top.addWidget(self.pause_btn)
        root.addLayout(top)

        self.banner = QFrame()
        self.banner.setObjectName("card")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, stretch=1)
        self.grant_btn = QPushButton("Grant access")
        self.grant_btn.setObjectName("accent")
        self.grant_btn.clicked.connect(self._grant)
        bl.addWidget(self.grant_btn)
        root.addWidget(self.banner)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Process", "PID", "Download", "Upload"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        self.refresh_banner()

    def refresh_banner(self):
        if nethogs_path() is None:
            self.banner.show()
            self.banner_text.setText(
                "nethogs is not installed. Install it to see per-process "
                "usage (e.g. <b>sudo dnf install nethogs</b>)."
            )
            self.grant_btn.hide()
            self.pause_btn.setEnabled(False)
        elif has_capabilities():
            self.banner.hide()
            self.pause_btn.setEnabled(True)
        else:
            self.banner.show()
            self.banner_text.setText(
                "Per-app tracking needs elevated capabilities. Click "
                "<b>Grant access</b> to authorize nethogs once (uses pkexec)."
            )
            self.grant_btn.show()
            self.pause_btn.setEnabled(False)

    def set_tracking_state(self, active):
        self._tracking = active
        self.pause_btn.setText("Pause" if active else "Resume")
        if not has_capabilities():
            return
        self.status.setText(
            "Tracking in background — rates refresh every " f"{TRACK_INTERVAL}s."
            if active
            else "Tracking paused."
        )

    def _grant(self):
        self.grant_btn.setEnabled(False)
        self.status.setText("Requesting authorization…")
        QApplication.processEvents()
        ok, msg = grant_capabilities()
        self.grant_btn.setEnabled(True)
        self.status.setText(msg)
        self.refresh_banner()
        if ok:
            self.access_granted.emit()

    def _toggle(self):
        if not has_capabilities():
            QMessageBox.information(
                self,
                "Access needed",
                "nethogs needs capabilities first. Use Grant access.",
            )
            return
        self.tracking_toggled.emit(not self._tracking)

    def update_live(self, rows):
        rows = [r for r in rows if r["sent"] > 0 or r["recv"] > 0]
        rows.sort(key=lambda r: r["sent"] + r["recv"], reverse=True)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, _cell(r["program"]))
            self.table.setItem(i, 1, _cell(r["pid"], align=Qt.AlignCenter))
            self.table.setItem(
                i,
                2,
                _cell(human_rate(r["recv"]), RX_COLOR, Qt.AlignRight | Qt.AlignVCenter),
            )
            self.table.setItem(
                i,
                3,
                _cell(human_rate(r["sent"]), TX_COLOR, Qt.AlignRight | Qt.AlignVCenter),
            )
        if not rows and self._tracking:
            self.status.setText("Tracking… no active traffic right now.")


class AppsTab(QWidget):
    """Accumulated per-app usage (today / this month) from the local DB."""

    def __init__(self, usage):
        super().__init__()
        self.usage = usage
        self.iface = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Usage by App")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel("Period:"))
        self.period = QComboBox()
        self.period.addItem("Today", "day")
        self.period.addItem("This month", "month")
        self.period.currentIndexChanged.connect(self.reload)
        top.addWidget(self.period)
        self.export_btn = QPushButton("Export ▾")
        export_menu = QMenu(self.export_btn)
        export_menu.addAction("CSV…", lambda: self._export("csv"))
        export_menu.addAction("JSON…", lambda: self._export("json"))
        self.export_btn.setMenu(export_menu)
        top.addWidget(self.export_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        self.summary = StatCard("Tracked total")
        root.addWidget(self.summary)
        self._rows = []

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["App", "Download", "Upload", "Total / share"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, stretch=1)

        self.note = QLabel(
            "Counts only since tracking started — it cannot split usage that "
            "happened before. Some traffic stays unattributed by nethogs."
        )
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

    def set_iface(self, iface):
        self.iface = iface
        self.reload()

    def reload(self):
        if self.period.currentData() == "month":
            rows = self.usage.month_totals(self.iface)
        else:
            rows = self.usage.day_totals(self.iface)
        self._rows = rows
        grand = sum(r["total"] for r in rows) or 1
        self.summary.set_value(f"{human_bytes(grand if rows else 0)}")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            share = r["total"] / grand * 100
            self.table.setItem(i, 0, _cell(r["app"]))
            self.table.setItem(
                i,
                1,
                _cell(human_bytes(r["rx"]), RX_COLOR, Qt.AlignRight | Qt.AlignVCenter),
            )
            self.table.setItem(
                i,
                2,
                _cell(human_bytes(r["tx"]), TX_COLOR, Qt.AlignRight | Qt.AlignVCenter),
            )
            self.table.setItem(
                i,
                3,
                _cell(
                    f"{human_bytes(r['total'])}  ({share:.0f}%)",
                    align=Qt.AlignRight | Qt.AlignVCenter,
                ),
            )
        if not rows:
            self.summary.set_value("—")

    def _export(self, fmt):
        if not self._rows:
            self.note.setText("Nothing to export yet for this period.")
            return
        period = self.period.currentData()
        default = f"nettracker-apps-{period}-{self.iface or 'iface'}.{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export per-app usage", default, f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        try:
            if fmt == "csv":
                export.write_csv(
                    path,
                    ["app", "rx_bytes", "tx_bytes", "total_bytes"],
                    [
                        [r["app"], int(r["rx"]), int(r["tx"]), int(r["total"])]
                        for r in self._rows
                    ],
                )
            else:
                export.write_json(
                    path,
                    [
                        {
                            "app": r["app"],
                            "rx_bytes": int(r["rx"]),
                            "tx_bytes": int(r["tx"]),
                            "total_bytes": int(r["total"]),
                        }
                        for r in self._rows
                    ],
                )
            self.note.setText(f"Exported {len(self._rows)} apps to {path}")
        except OSError as exc:
            self.note.setText(f"Export failed: {exc}")

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        set_rate_unit(self.settings.get("rate_unit"))
        self._really_quit = False

        self.setWindowTitle("NetTracker — Internet Usage")
        self.resize(940, 700)
        self.setStyleSheet(STYLE)
        self.icon = make_icon(64)
        self.setWindowIcon(self.icon)

        self.usage = UsageDB()
        self.monitor = None  # shared background nethogs

        self.tabs = QTabWidget()
        self.live = LiveTab()
        self.history = HistoryTab(self.settings)
        self.apps = AppsTab(self.usage)
        self.process = ProcessTab()
        self.tabs.addTab(self.live, "Live")
        self.tabs.addTab(self.history, "History")
        self.tabs.addTab(self.apps, "Apps")
        self.tabs.addTab(self.process, "Processes")
        self.setCentralWidget(self.tabs)

        self._build_menu()
        self._build_tray()

        self.live.speed_updated.connect(self._on_speed)
        self.history.cap_changed.connect(self._on_cap)
        self.history.day_total_changed.connect(self._check_daily_alert)
        self.live.combo.currentIndexChanged.connect(self._sync_iface)
        self.process.access_granted.connect(self._on_access_granted)
        self.process.tracking_toggled.connect(self._set_tracking)

        # Persist an icon file and expose whether we should launch hidden.
        autostart.save_icon(self.icon)
        want_hidden = bool(self.settings.get("start_minimized"))
        self.start_hidden = want_hidden and self.tray is not None

        interfaces = sources.list_interfaces()
        self.live.populate(interfaces)
        self.live.select_interface(self.settings.get("interface"))
        # Guarantee the other tabs are initialised even if selecting the
        # saved interface did not change the combo index (no signal fired).
        self._sync_iface(self.live.combo.currentIndex())
        self.live.start()

        # Start per-app tracking in the background if allowed and granted.
        if self.settings.get("track_apps") and has_capabilities():
            self._start_tracking()
        self.process.set_tracking_state(self._tracking_active())

        # periodic cap/history refresh even when the window is hidden
        self.cap_timer = QTimer(self)
        self.cap_timer.setInterval(120_000)
        self.cap_timer.timeout.connect(self.history.reload)
        self.cap_timer.start()

    # ---- menu & tray -------------------------------------------------

    def _build_menu(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("File")
        act_hide = QAction("Hide to tray", self)
        act_hide.triggered.connect(self.hide)
        file_menu.addAction(act_hide)
        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_quit)

        view_menu = bar.addMenu("View")
        units_menu = view_menu.addMenu("Speed units")
        self.unit_group = QActionGroup(self)
        for label, mode in (
            ("Bytes/s (KiB/s)", "bytes"),
            ("Bits/s (Mbps)", "bits"),
        ):
            act = QAction(label, self, checkable=True)
            act.setData(mode)
            act.setChecked(self.settings.get("rate_unit") == mode)
            act.triggered.connect(lambda _c, m=mode: self._set_units(m))
            self.unit_group.addAction(act)
            units_menu.addAction(act)
        view_menu.addSeparator()
        act_refresh = QAction("Refresh history", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.history.reload)
        view_menu.addAction(act_refresh)

        settings_menu = bar.addMenu("Settings")
        act_cap = QAction("Data cap && alerts…", self)
        act_cap.triggered.connect(self._open_cap_dialog)
        settings_menu.addAction(act_cap)
        self.act_track = QAction("Track per-app usage", self, checkable=True)
        self.act_track.setChecked(bool(self.settings.get("track_apps")))
        self.act_track.toggled.connect(self._set_tracking)
        settings_menu.addAction(self.act_track)
        settings_menu.addSeparator()
        self.act_autostart = QAction("Launch on login", self, checkable=True)
        self.act_autostart.setChecked(autostart.is_enabled())
        self.act_autostart.toggled.connect(self._set_autostart)
        settings_menu.addAction(self.act_autostart)
        self.act_minimized = QAction("Start minimized to tray", self, checkable=True)
        self.act_minimized.setChecked(bool(self.settings.get("start_minimized")))
        self.act_minimized.toggled.connect(
            lambda v: self.settings.set("start_minimized", bool(v))
        )
        settings_menu.addAction(self.act_minimized)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("NetTracker")
        menu = QMenu()
        self.tray_show = QAction("Show NetTracker", self)
        self.tray_show.triggered.connect(self._show_window)
        menu.addAction(self.tray_show)
        menu.addSeparator()
        tray_quit = QAction("Quit", self)
        tray_quit.triggered.connect(self.quit_app)
        menu.addAction(tray_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---- handlers ----------------------------------------------------

    def _set_units(self, mode):
        set_rate_unit(mode)
        self.settings.set("rate_unit", mode)
        self.live.refresh_units()

    def _set_autostart(self, enabled):
        if enabled:
            icon_path = autostart.save_icon(self.icon)
            autostart.enable(icon_path)
        else:
            autostart.disable()

    def _open_cap_dialog(self):
        dlg = CapDialog(self.settings, self)
        if dlg.exec_() == QDialog.Accepted:
            dlg.apply()
            self.history.reload()

    def _sync_iface(self, _index):
        iface = self.live.combo.currentData()
        self.settings.set("interface", iface)
        self.history.set_iface(iface)
        self.apps.set_iface(iface)
        # Re-point the background tracker at the newly selected interface.
        if self._tracking_active():
            self._start_tracking()

    # ---- per-app tracking -------------------------------------------

    def _tracking_active(self):
        return self.monitor is not None and self.monitor.is_running()

    def _on_access_granted(self):
        if self.settings.get("track_apps"):
            self._start_tracking()
        self.process.set_tracking_state(self._tracking_active())

    def _set_tracking(self, enabled):
        self.settings.set("track_apps", bool(enabled))
        if hasattr(self, "act_track"):
            self.act_track.setChecked(bool(enabled))
        if enabled:
            if has_capabilities():
                self._start_tracking()
            else:
                self.process.refresh_banner()
        else:
            self._stop_tracking()
        self.process.set_tracking_state(self._tracking_active())

    def _start_tracking(self):
        self._stop_tracking()
        iface = self.live.iface
        if not iface or not has_capabilities():
            return
        self.monitor = NethogsMonitor(iface=iface, delay=TRACK_INTERVAL, parent=self)
        self.monitor.updated.connect(self._on_samples)
        self.monitor.error.connect(self._on_track_error)
        self.monitor.start()

    def _stop_tracking(self):
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

    def _on_samples(self, rows):
        iface = self.live.iface
        for r in rows:
            # rate (bytes/s) integrated over the sample interval -> bytes
            self.usage.add(
                iface,
                r["program"],
                r["recv"] * TRACK_INTERVAL,
                r["sent"] * TRACK_INTERVAL,
            )
        self.usage.commit()
        self.process.update_live(rows)
        self._check_app_alerts()
        if self.apps.isVisible():
            self.apps.reload()

    # ---- alerts ------------------------------------------------------

    def _notify(self, msg, title="NetTracker"):
        if self.tray:
            self.tray.showMessage(title, msg, self.icon, 8000)

    def _check_daily_alert(self, today_total):
        if not self.settings.get("daily_alert_enabled"):
            return
        threshold = float(self.settings.get("daily_alert_gb")) * 1e9
        if today_total < threshold:
            return
        day = self.usage.today()
        notified = dict(self.settings.get("daily_notified") or {})
        if notified.get(day):
            return
        notified = {day: True}  # keep only the current day
        self.settings.set("daily_notified", notified)
        self._notify(
            f"Daily usage passed {self.settings.get('daily_alert_gb'):g} GB "
            f"({human_gb(today_total)} today)."
        )

    def _check_app_alerts(self):
        if not self.settings.get("app_alert_enabled"):
            return
        threshold = float(self.settings.get("app_alert_gb")) * 1e9
        day = self.usage.today()
        store = dict(self.settings.get("app_notified") or {})
        done = list(store.get(day, []))
        changed = False
        for row in self.usage.day_totals(self.live.iface):
            if row["total"] >= threshold and row["app"] not in done:
                done.append(row["app"])
                changed = True
                self._notify(
                    f"{row['app']} passed "
                    f"{self.settings.get('app_alert_gb'):g} GB today "
                    f"({human_gb(row['total'])})."
                )
        if changed:
            self.settings.set("app_notified", {day: done})

    def _on_track_error(self, msg):
        self._stop_tracking()
        self.process.status.setText(msg)
        self.process.refresh_banner()
        self.process.set_tracking_state(False)

    def _on_speed(self, rx_rate, tx_rate):
        if self.tray:
            self.tray.setToolTip(
                f"NetTracker — {self.live.iface or '?'}\n"
                f"↓ {human_rate(rx_rate)}   ↑ {human_rate(tx_rate)}"
            )

    def _on_cap(self, info):
        if not info or not self.tray:
            return
        cycle = info["cycle_key"]
        notified = dict(self.settings.get("cap_notified") or {})
        done = list(notified.get(cycle, []))
        pct = info["fraction"] * 100
        changed = False
        for threshold in CAP_THRESHOLDS:
            if pct >= threshold and threshold not in done:
                done.append(threshold)
                changed = True
                if threshold >= 100:
                    msg = (
                        f"Data cap reached: {human_gb(info['used'])} of "
                        f"{info['limit_gb']:g} GB used."
                    )
                else:
                    msg = (
                        f"{threshold}% of your {info['limit_gb']:g} GB cap "
                        f"used ({human_gb(info['used'])})."
                    )
                self.tray.showMessage("NetTracker", msg, self.icon, 8000)
        if changed:
            notified[cycle] = done
            self.settings.set("cap_notified", notified)

    # ---- lifecycle ---------------------------------------------------

    def quit_app(self):
        self._really_quit = True
        self.close()

    def closeEvent(self, event):
        if (
            not self._really_quit
            and self.tray is not None
            and self.settings.get("close_to_tray")
        ):
            event.ignore()
            self.hide()
            if not self.settings.get("tray_hint_shown"):
                self.tray.showMessage(
                    "NetTracker",
                    "Still running in the tray. " "Right-click the icon to quit.",
                    self.icon,
                    5000,
                )
                self.settings.set("tray_hint_shown", True)
            return
        self.live.stop()
        self._stop_tracking()
        self.usage.close()
        if self.tray:
            self.tray.hide()
        super().closeEvent(event)

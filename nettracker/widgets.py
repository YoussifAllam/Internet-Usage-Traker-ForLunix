"""Custom QPainter chart widgets (no external charting dependency)."""

from collections import deque

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import QSizePolicy, QWidget

from .utils import human_bytes, human_rate

RX_COLOR = QColor("#4fc3f7")  # download – blue
TX_COLOR = QColor("#81c784")  # upload   – green
GRID = QColor(255, 255, 255, 22)
TEXT = QColor("#9aa4b2")


class LiveGraph(QWidget):
    """Scrolling line graph of download/upload rate over the last N samples."""

    def __init__(self, capacity=60, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.rx = deque([0.0] * capacity, maxlen=capacity)
        self.tx = deque([0.0] * capacity, maxlen=capacity)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add_sample(self, rx_rate, tx_rate):
        self.rx.append(float(rx_rate))
        self.tx.append(float(tx_rate))
        self.update()

    def clear(self):
        self.rx = deque([0.0] * self.capacity, maxlen=self.capacity)
        self.tx = deque([0.0] * self.capacity, maxlen=self.capacity)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        p.fillRect(self.rect(), QColor("#11151c"))

        peak = max(max(self.rx), max(self.tx), 1.0)
        # Round the scale up to something tidy.
        scale = _nice_ceiling(peak)

        # Horizontal grid lines + labels.
        p.setFont(QFont("", 8))
        for i in range(5):
            y = rect.top() + rect.height() * i / 4.0
            p.setPen(QPen(GRID, 1))
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            value = scale * (1 - i / 4.0)
            p.setPen(QPen(TEXT))
            p.drawText(
                QRectF(rect.left(), y - 14, rect.width() - 4, 14),
                Qt.AlignRight | Qt.AlignVCenter,
                human_rate(value),
            )

        self._draw_series(p, rect, self.rx, scale, RX_COLOR)
        self._draw_series(p, rect, self.tx, scale, TX_COLOR)
        p.end()

    def _draw_series(self, p, rect, data, scale, color):
        n = len(data)
        if n < 2:
            return
        dx = rect.width() / (n - 1)

        def point(i, value):
            x = rect.left() + dx * i
            y = rect.bottom() - (value / scale) * rect.height()
            return QPointF(x, y)

        line = QPainterPath()
        line.moveTo(point(0, data[0]))
        for i in range(1, n):
            line.lineTo(point(i, data[i]))

        fill = QPainterPath(line)
        fill.lineTo(point(n - 1, 0))
        fill.lineTo(point(0, 0))
        fill.closeSubpath()

        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        c1 = QColor(color)
        c1.setAlpha(90)
        c2 = QColor(color)
        c2.setAlpha(10)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.fillPath(fill, grad)

        p.setPen(QPen(color, 2))
        p.drawPath(line)


class BarChart(QWidget):
    """Stacked bars (rx + tx) with labels, for daily/monthly history."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []  # list of {label, rx, tx, total}
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_items(self, items):
        self.items = list(items)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#11151c"))
        rect = self.rect().adjusted(10, 14, -10, -24)

        if not self.items:
            p.setPen(QPen(TEXT))
            p.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            p.end()
            return

        peak = max((it["total"] for it in self.items), default=1) or 1
        scale = _nice_ceiling(peak)
        n = len(self.items)
        slot = rect.width() / n
        bar_w = min(46, slot * 0.6)

        p.setFont(QFont("", 8))
        # baseline + scale ticks
        for i in range(5):
            y = rect.top() + rect.height() * i / 4.0
            p.setPen(QPen(GRID, 1))
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            p.setPen(QPen(TEXT))
            p.drawText(
                QRectF(rect.left(), y - 14, rect.width(), 14),
                Qt.AlignRight | Qt.AlignVCenter,
                human_bytes(scale * (1 - i / 4.0)),
            )

        for i, it in enumerate(self.items):
            cx = rect.left() + slot * i + slot / 2.0
            x = cx - bar_w / 2.0
            rx_h = (it["rx"] / scale) * rect.height()
            tx_h = (it["tx"] / scale) * rect.height()
            rx_top = rect.bottom() - rx_h
            tx_top = rx_top - tx_h
            p.fillRect(QRectF(x, rx_top, bar_w, rx_h), RX_COLOR)
            p.fillRect(QRectF(x, tx_top, bar_w, tx_h), TX_COLOR)

            p.setPen(QPen(TEXT))
            p.drawText(
                QRectF(cx - slot / 2, rect.bottom() + 2, slot, 18),
                Qt.AlignCenter,
                it["label"],
            )
        p.end()


def _nice_ceiling(value):
    """Round a value up to 1/2/5 * 10^k for tidy axis scaling."""
    if value <= 0:
        return 1.0
    import math

    exp = math.floor(math.log10(value))
    base = 10**exp
    for mult in (1, 2, 5, 10):
        if value <= mult * base:
            return mult * base
    return 10 * base


class CapBar(QWidget):
    """Horizontal data-cap progress bar that recolors by fill level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.caption = ""
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_progress(self, fraction, caption=""):
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.caption = caption
        self.update()

    def _fill_color(self):
        if self.fraction >= 1.0:
            return QColor("#f85149")  # red
        if self.fraction >= 0.8:
            return QColor("#e3b341")  # amber
        return QColor("#3fb950")  # green

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        radius = r.height() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#11151c"))
        p.drawRoundedRect(r, radius, radius)
        if self.fraction > 0:
            fill = QRectF(r)
            fill.setWidth(max(r.height(), r.width() * self.fraction))
            p.setBrush(self._fill_color())
            p.drawRoundedRect(fill, radius, radius)
        if self.caption:
            p.setPen(QPen(QColor("#e6edf3")))
            p.setFont(QFont("", 9, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, self.caption)
        p.end()


def make_icon(size=64):
    """Build the app/tray icon (down+up arrows) with QPainter — no asset."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1f6feb"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.22, size * 0.22)

    pen = QPen(QColor("white"), max(2, size // 16))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    q = size / 4.0
    # download arrow (left, pointing down)
    p.drawLine(int(q), int(q * 0.9), int(q), int(q * 3.0))
    p.drawPolyline(
        QPointF(q * 0.6, q * 2.4),
        QPointF(q, q * 3.05),
        QPointF(q * 1.4, q * 2.4),
    )
    # upload arrow (right, pointing up)
    p.drawLine(int(q * 3), int(q * 3.1), int(q * 3), int(q))
    p.drawPolyline(
        QPointF(q * 2.6, q * 1.6),
        QPointF(q * 3, q * 0.95),
        QPointF(q * 3.4, q * 1.6),
    )
    p.end()
    return QIcon(pix)

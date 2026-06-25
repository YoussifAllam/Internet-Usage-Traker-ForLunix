"""Per-app usage accumulator backed by SQLite.

nethogs only reports live rates, so we integrate those rates over time
(bytes ~= rate * interval) and accumulate them per (day, interface, app).
This builds up Today / This-month per-app totals from when tracking starts.
"""

import datetime
import os
import sqlite3


def _db_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "nettracker", "usage.db")


class UsageDB:
    def __init__(self):
        self.path = _db_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS app_usage ("
            " day TEXT, iface TEXT, app TEXT,"
            " rx REAL DEFAULT 0, tx REAL DEFAULT 0,"
            " PRIMARY KEY (day, iface, app))"
        )
        self.conn.commit()

    @staticmethod
    def today():
        return datetime.date.today().isoformat()

    @staticmethod
    def this_month():
        return datetime.date.today().strftime("%Y-%m")

    def add(self, iface, app, rx_bytes, tx_bytes, day=None):
        if rx_bytes <= 0 and tx_bytes <= 0:
            return
        day = day or self.today()
        self.conn.execute(
            "INSERT INTO app_usage (day, iface, app, rx, tx)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(day, iface, app) DO UPDATE SET"
            " rx = rx + excluded.rx, tx = tx + excluded.tx",
            (day, iface or "", app, float(rx_bytes), float(tx_bytes)),
        )

    def commit(self):
        self.conn.commit()

    def _rows(self, where, params):
        cur = self.conn.execute(
            "SELECT app, SUM(rx) AS rx, SUM(tx) AS tx FROM app_usage"
            f" WHERE {where} GROUP BY app"
            " ORDER BY SUM(rx) + SUM(tx) DESC",
            params,
        )
        out = []
        for app, rx, tx in cur.fetchall():
            rx = rx or 0
            tx = tx or 0
            out.append({"app": app, "rx": rx, "tx": tx, "total": rx + tx})
        return out

    def day_totals(self, iface, day=None):
        day = day or self.today()
        return self._rows("day = ? AND iface = ?", (day, iface or ""))

    def month_totals(self, iface, ym=None):
        ym = ym or self.this_month()
        return self._rows("day LIKE ? AND iface = ?", (ym + "%", iface or ""))

    def day_totals_all(self, day=None):
        """Per-app totals for one day across every interface."""
        day = day or self.today()
        return self._rows("day = ?", (day,))

    def month_totals_all(self, ym=None):
        """Per-app totals for one month across every interface."""
        ym = ym or self.this_month()
        return self._rows("day LIKE ?", (ym + "%",))

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            pass

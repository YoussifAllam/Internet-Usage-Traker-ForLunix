"""Data sources: network interfaces, live counters, and vnstat history."""

import json
import os
import subprocess

SYS_NET = "/sys/class/net"


def list_interfaces():
    """Return a list of dicts for real (non-loopback) interfaces.

    Each dict: {name, state, is_up}. Up interfaces are listed first.
    """
    result = []
    try:
        names = sorted(os.listdir(SYS_NET))
    except OSError:
        names = []
    for name in names:
        if name == "lo":
            continue
        path = os.path.join(SYS_NET, name, "operstate")
        state = _read_text(path) or "unknown"
        result.append({"name": name, "state": state, "is_up": state == "up"})
    # up interfaces first, then alphabetical
    result.sort(key=lambda d: (not d["is_up"], d["name"]))
    return result


def read_counters(iface):
    """Return (rx_bytes, tx_bytes) for an interface, or (None, None)."""
    rx = _read_text(os.path.join(SYS_NET, iface, "statistics", "rx_bytes"))
    tx = _read_text(os.path.join(SYS_NET, iface, "statistics", "tx_bytes"))
    try:
        return int(rx), int(tx)
    except (TypeError, ValueError):
        return None, None


def _read_text(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


class VnstatError(Exception):
    pass


def vnstat_available():
    return _which("vnstat") is not None


def fetch_vnstat(iface=None):
    """Run `vnstat --json` and return the parsed dict for one interface.

    If iface is None, returns the first interface in the database.
    Raises VnstatError on failure.
    """
    cmd = ["vnstat", "--json"]
    if iface:
        cmd += ["-i", iface]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VnstatError(str(exc))
    if out.returncode != 0:
        raise VnstatError(out.stderr.strip() or "vnstat failed")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise VnstatError(f"bad JSON from vnstat: {exc}")

    interfaces = data.get("interfaces", [])
    if not interfaces:
        raise VnstatError("vnstat has no data for this interface yet")
    if iface:
        for entry in interfaces:
            if entry.get("name") == iface:
                return entry
        raise VnstatError(f"no vnstat data for {iface}")
    return interfaces[0]


def parse_history(entry):
    """Turn a vnstat interface entry into a friendly summary dict."""
    traffic = entry.get("traffic", {})

    def rows(key):
        out = []
        for item in traffic.get(key, []):
            date = item.get("date", {})
            label = _date_label(date, item.get("time"))
            out.append(
                {
                    "label": label,
                    "date": (
                        date.get("year"),
                        date.get("month"),
                        date.get("day"),
                    ),
                    "rx": item.get("rx", 0),
                    "tx": item.get("tx", 0),
                    "total": item.get("rx", 0) + item.get("tx", 0),
                }
            )
        return out

    total = traffic.get("total", {})
    days = rows("day")
    months = rows("month")
    top = rows("top")

    today = days[-1] if days else None
    this_month = months[-1] if months else None

    return {
        "name": entry.get("name", "?"),
        "total": {
            "rx": total.get("rx", 0),
            "tx": total.get("tx", 0),
            "total": total.get("rx", 0) + total.get("tx", 0),
        },
        "today": today,
        "this_month": this_month,
        "days": days,
        "months": months,
        "top": top,
    }


def _date_label(date, time=None):
    y = date.get("year")
    m = date.get("month")
    d = date.get("day")
    if d:
        label = f"{m:02d}/{d:02d}" if m else str(d)
    elif m:
        label = f"{y}-{m:02d}"
    else:
        label = str(y)
    if time:
        label += f" {time.get('hour', 0):02d}:{time.get('minute', 0):02d}"
    return label


def cycle_start(billing_day, today):
    """Return the date the current billing cycle started.

    billing_day: 1..28. today: datetime.date.
    """
    import datetime

    day = max(1, min(28, int(billing_day)))
    if today.day >= day:
        return datetime.date(today.year, today.month, day)
    year = today.year - 1 if today.month == 1 else today.year
    month = 12 if today.month == 1 else today.month - 1
    return datetime.date(year, month, day)


def cycle_usage(days, billing_day, today=None):
    """Sum rx+tx (bytes) of daily rows on/after the cycle start.

    Returns (used_bytes, start_date). Rows carry a 'date' (y, m, d).
    """
    import datetime

    if today is None:
        today = datetime.date.today()
    start = cycle_start(billing_day, today)
    used = 0
    for row in days:
        y, m, d = row.get("date", (None, None, None))
        if None in (y, m, d):
            continue
        if datetime.date(y, m, d) >= start:
            used += row.get("total", 0)
    return used, start


def _which(prog):
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, prog)
        if os.access(candidate, os.X_OK):
            return candidate
    return None

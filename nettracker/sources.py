"""Data sources: network interfaces, live counters, and vnstat history."""

import json
import os
import subprocess

SYS_NET = "/sys/class/net"

# Sentinel selecting the combined total of every interface.
ALL_IFACES = "__all__"
ALL_LABEL = "All interfaces"


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
    if iface == ALL_IFACES:
        return read_total_counters()
    rx = _read_text(os.path.join(SYS_NET, iface, "statistics", "rx_bytes"))
    tx = _read_text(os.path.join(SYS_NET, iface, "statistics", "tx_bytes"))
    try:
        return int(rx), int(tx)
    except (TypeError, ValueError):
        return None, None


def read_total_counters():
    """Summed (rx_bytes, tx_bytes) across every real interface."""
    total_rx = total_tx = 0
    any_ok = False
    for info in list_interfaces():
        rx = _read_text(os.path.join(SYS_NET, info["name"], "statistics", "rx_bytes"))
        tx = _read_text(os.path.join(SYS_NET, info["name"], "statistics", "tx_bytes"))
        try:
            total_rx += int(rx)
            total_tx += int(tx)
            any_ok = True
        except (TypeError, ValueError):
            continue
    return (total_rx, total_tx) if any_ok else (None, None)


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
            time = item.get("time")
            y = date.get("year")
            m = date.get("month")
            d = date.get("day")
            hh = time.get("hour") if time else None
            out.append(
                {
                    "label": _date_label(date, time),
                    "date": (y, m, d),
                    # unique, sortable key (per-hour when time is present)
                    "key": (y or 0, m or 0, d or 0, hh if hh is not None else -1),
                    "hour": hh,
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
    hours = rows("hour")
    for r in hours:
        if r["hour"] is not None:
            r["label"] = f"{r['hour']:02d}:00"

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
        "hours": hours,
        "top": top,
    }


def fetch_all_history():
    """Merged history across every interface in the vnstat database."""
    cmd = ["vnstat", "--json"]
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
        raise VnstatError("vnstat has no data yet")
    return merge_histories([parse_history(e) for e in interfaces])


def _merge_rows(rowlists):
    """Sum rows from several interfaces, keyed per row, sorted ascending."""
    acc = {}
    for rows in rowlists:
        for r in rows:
            key = r["key"]
            slot = acc.setdefault(
                key,
                {
                    "label": r["label"],
                    "date": r["date"],
                    "key": key,
                    "hour": r.get("hour"),
                    "rx": 0,
                    "tx": 0,
                    "total": 0,
                },
            )
            slot["rx"] += r["rx"]
            slot["tx"] += r["tx"]
            slot["total"] += r["total"]
    return [acc[k] for k in sorted(acc)]


def merge_histories(hists):
    """Combine several parse_history() dicts into one aggregate dict."""
    days = _merge_rows([h["days"] for h in hists])
    months = _merge_rows([h["months"] for h in hists])
    hours = _merge_rows([h.get("hours", []) for h in hists])
    top = sorted(
        _merge_rows([h["top"] for h in hists]),
        key=lambda r: r["total"],
        reverse=True,
    )[:10]
    total_rx = sum(h["total"]["rx"] for h in hists)
    total_tx = sum(h["total"]["tx"] for h in hists)
    return {
        "name": ALL_LABEL,
        "total": {
            "rx": total_rx,
            "tx": total_tx,
            "total": total_rx + total_tx,
        },
        "today": days[-1] if days else None,
        "this_month": months[-1] if months else None,
        "days": days,
        "months": months,
        "hours": hours,
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


def _add_month(d):
    import datetime

    month = d.month + 1
    year = d.year
    if month > 12:
        month = 1
        year += 1
    return datetime.date(year, month, min(d.day, 28))


def forecast(used_bytes, limit_bytes, start, today=None):
    """Project end-of-cycle usage and the date the cap would be hit.

    Returns a dict: avg_per_day, projected_total, cycle_end (inclusive),
    hit_date (or None), and over_by (projected - limit, can be negative).
    """
    import datetime
    import math

    if today is None:
        today = datetime.date.today()
    next_start = _add_month(start)
    cycle_len = max(1, (next_start - start).days)
    days_elapsed = max(1, (today - start).days + 1)
    avg = used_bytes / days_elapsed
    projected = avg * cycle_len

    hit_date = None
    if used_bytes >= limit_bytes > 0:
        hit_date = today
    elif avg > 0 and limit_bytes > 0:
        days_to = math.ceil((limit_bytes - used_bytes) / avg)
        candidate = today + datetime.timedelta(days=days_to)
        if candidate < next_start:
            hit_date = candidate

    return {
        "avg_per_day": avg,
        "projected_total": projected,
        "cycle_end": next_start - datetime.timedelta(days=1),
        "hit_date": hit_date,
        "over_by": projected - limit_bytes,
    }


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

"""Live network connections per process, parsed from `ss`.

No root needed for your own sockets. Each row identifies the app, protocol,
and the remote endpoint it is talking to.
"""

import os
import re
import subprocess

_PROC_RE = re.compile(r'"(?P<name>[^"]+)",pid=(?P<pid>\d+)')

_LOCAL_PREFIXES = ("127.", "::1", "0.0.0.0", "*", "::")


def ss_available():
    for path in os.environ.get("PATH", "").split(os.pathsep):
        if os.access(os.path.join(path, "ss"), os.X_OK):
            return True
    return False


def list_connections(established_only=True):
    """Return a list of connection dicts sorted by app then remote.

    Each dict: {app, pid, proto, state, laddr, raddr, rport}.
    """
    try:
        out = subprocess.run(
            ["ss", "-tunpH"], capture_output=True, text=True, timeout=8
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.stdout.splitlines():
        row = _parse_line(line)
        if row is None:
            continue
        if established_only and row["state"] != "ESTAB":
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r["app"].lower(), r["raddr"]))
    return rows


def _parse_line(line):
    parts = line.split()
    if len(parts) < 6:
        return None
    proto, state, _rq, _sq, local, peer = parts[:6]
    proc = parts[6] if len(parts) > 6 else ""

    raddr, rport = _split_host_port(peer)
    if not raddr or raddr.startswith(_LOCAL_PREFIXES):
        return None
    laddr, _lport = _split_host_port(local)

    app, pid = "—", ""
    m = _PROC_RE.search(proc)
    if m:
        app, pid = m.group("name"), m.group("pid")

    return {
        "app": app,
        "pid": pid,
        "proto": proto,
        "state": state,
        "laddr": laddr,
        "raddr": raddr,
        "rport": rport,
    }


def _split_host_port(addr):
    """Split `host:port`, tolerating IPv6 and a `%iface` suffix."""
    addr = addr.split("%", 1)[0]
    if ":" not in addr:
        return addr, ""
    host, port = addr.rsplit(":", 1)
    host = host.strip("[]")
    return host, port

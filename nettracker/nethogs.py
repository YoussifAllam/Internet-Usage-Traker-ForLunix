"""Per-process network usage via nethogs (trace mode), driven by QProcess."""

import os
import subprocess

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

NETHOGS_BIN = "/usr/bin/nethogs"
CAPS = "cap_net_admin,cap_net_raw,cap_dac_read_search,cap_sys_ptrace+ep"


def nethogs_path():
    if os.access(NETHOGS_BIN, os.X_OK):
        return NETHOGS_BIN
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, "nethogs")
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def has_capabilities():
    """True if nethogs can capture without root (caps set, or we are root)."""
    if os.geteuid() == 0:
        return True
    binary = nethogs_path()
    if not binary:
        return False
    try:
        out = subprocess.run(
            ["getcap", binary], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "cap_net_raw" in out.stdout


def grant_capabilities():
    """Use pkexec to grant nethogs the needed capabilities. Blocking.

    Returns (ok, message).
    """
    binary = nethogs_path()
    if not binary:
        return False, "nethogs is not installed"
    try:
        out = subprocess.run(
            ["pkexec", "setcap", CAPS, binary],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if out.returncode == 0:
        return True, "Capabilities granted."
    if out.returncode == 126:
        return False, "Authorization cancelled."
    return False, out.stderr.strip() or "Failed to set capabilities."


class NethogsMonitor(QObject):
    """Runs `nethogs -t` and emits parsed per-process rows.

    updated(list[dict]) -- each dict: {program, pid, uid, sent, recv}
                           sent/recv are bytes per second.
    error(str)
    """

    updated = pyqtSignal(list)
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, iface=None, delay=2, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.delay = delay
        self._proc = None
        self._block = []
        self._buffer = ""

    def is_running(self):
        return (
            self._proc is not None and self._proc.state() != QProcess.NotRunning  # noqa
        )

    def start(self):
        if self.is_running():
            return
        binary = nethogs_path()
        if not binary:
            self.error.emit("nethogs is not installed.")
            return
        self._block = []
        self._buffer = ""
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyRead.connect(self._on_ready)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)
        # -t trace mode, -d delay between refreshes
        args = ["-t", "-d", str(self.delay)]
        if self.iface:
            args.append(self.iface)
        self._proc.start(binary, args)

    def stop(self):
        if self._proc is not None:
            self._proc.readyRead.disconnect()
            self._proc.terminate()
            if not self._proc.waitForFinished(1500):
                self._proc.kill()
            self._proc = None
            self.stopped.emit()

    def _on_ready(self):
        self._buffer += bytes(self._proc.readAll()).decode("utf-8", "replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line):
        if not line:
            return
        low = line.lower()
        if low.startswith("refreshing"):
            # End of a block: flush whatever we accumulated.
            if self._block:
                self.updated.emit(self._block)
            self._block = []
            return
        if (
            low.startswith("unknown tcp")
            or low.startswith("waiting")  # noqa
            or "error" in low  # noqa
            and "/" not in line  # noqa
        ):
            return
        # Format: program/pid/uid<TAB>sent_KB/s<TAB>recv_KB/s
        parts = line.split("\t")
        if len(parts) < 3:
            return
        ident = parts[0]
        try:
            sent = float(parts[1]) * 1024.0  # KB/s -> bytes/s
            recv = float(parts[2]) * 1024.0
        except ValueError:
            return
        program, pid, uid = _split_ident(ident)
        if program == "unknown TCP":
            return
        self._block.append(
            {
                "program": program,
                "pid": pid,
                "uid": uid,
                "sent": sent,
                "recv": recv,
            }
        )

    def _on_finished(self, code, status):
        if self._block:
            self.updated.emit(self._block)
            self._block = []

    def _on_proc_error(self, err):
        if err == QProcess.FailedToStart:
            self.error.emit("Failed to start nethogs.")


def _split_ident(ident):
    """`/usr/lib/firefox/firefox/1234/1000` -> (program, pid, uid).

    nethogs reports the full command line (path + args), so we keep only
    the executable's base name — e.g. a long `Code --foo=/x --bar` collapses
    to `Code`, and per-app totals aggregate across its helper processes.
    """
    bits = ident.rsplit("/", 2)
    if len(bits) == 3:
        program, pid, uid = bits
    else:
        program, pid, uid = ident, "?", "?"
    exe = program.strip().split(" ", 1)[0] if program.strip() else program
    name = os.path.basename(exe) or exe
    return name, pid, uid

"""Formatting helpers, with a switchable rate unit (bytes/s vs bits/s)."""

# Module-global rate unit, set from Settings at startup / when toggled.
_RATE_UNIT = "bytes"  # "bytes" or "bits"


def set_rate_unit(mode):
    global _RATE_UNIT
    if mode in ("bytes", "bits"):
        _RATE_UNIT = mode


def rate_unit():
    return _RATE_UNIT


def human_bytes(n):
    """Bytes -> binary human readable string, e.g. 1.50 GiB. (volumes)"""
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(n) < 1024.0:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} EiB"


def human_rate(bytes_per_sec):
    """Bytes/sec -> rate string honoring the current unit mode.

    bytes mode: binary  (B/s, KiB/s, MiB/s, ...)
    bits  mode: decimal (bit/s, kbit/s, Mbit/s, ...) — what 'Mbps' means.
    """
    if _RATE_UNIT == "bits":
        return _human_bits(bytes_per_sec * 8.0)
    return human_bytes(bytes_per_sec) + "/s"


def _human_bits(bits_per_sec):
    n = float(bits_per_sec)
    for unit in ("bit/s", "kbit/s", "Mbit/s", "Gbit/s", "Tbit/s"):
        if abs(n) < 1000.0:
            if unit == "bit/s":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1000.0
    return f"{n:.2f} Pbit/s"


def human_gb(n_bytes):
    """Bytes -> decimal GB string (for data-cap display vs a GB plan)."""
    return f"{n_bytes / 1_000_000_000.0:.2f} GB"

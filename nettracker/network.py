"""Identify the network behind an interface (Wi-Fi SSID or wired link).

Used to attribute usage to the network you're on, so a metered phone
hotspot stays separate from home Wi-Fi.
"""

import os
import subprocess

SYS_NET = "/sys/class/net"


def is_wireless(iface):
    return os.path.isdir(os.path.join(SYS_NET, iface, "wireless")) or os.path.isdir(
        os.path.join(SYS_NET, iface, "phy80211")
    )


def current_ssid():
    """SSID of the active Wi-Fi connection, or '' if none/unknown."""
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.stdout.splitlines():
        if line.startswith("yes:"):
            return line.split(":", 1)[1].strip()
    return ""


def network_for(iface):
    """Friendly network name for an interface.

    Wi-Fi -> the SSID (e.g. "Beta1"); wired -> "Ethernet (<iface>)".
    Falls back to the interface name when nothing better is known.
    """
    if not iface:
        return ""
    if is_wireless(iface):
        ssid = current_ssid()
        return ssid or f"Wi-Fi ({iface})"
    return f"Ethernet ({iface})"

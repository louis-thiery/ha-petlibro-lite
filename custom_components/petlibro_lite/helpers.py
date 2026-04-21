"""Pure-Python helpers that don't depend on Home Assistant.

Keeping these out of `coordinator.py` lets the unit test suite run without
installing `homeassistant`.
"""

from __future__ import annotations

import json
from typing import Any


def lan_scan(scantime: float = 6.0) -> dict[str, dict[str, Any]]:
    """Run tinytuya's UDP-broadcast device discovery and return a mapping
    `{devId: {"ip": str, "version": str | None, ...}}`.

    Blocking — call via `hass.async_add_executor_job` from async contexts.

    tinytuya listens for Tuya heartbeat broadcasts on UDP 6666/6667. The
    scan runs for `scantime` seconds and silently returns an empty dict
    if nothing is discovered (UDP broadcast blocked, multi-subnet
    network, etc.).
    """
    try:
        import tinytuya  # local import so the non-cloud code paths never pay for it
    except ImportError:
        return {}
    try:
        # Older tinytuya used kw `color`; newer uses `maxdevices`. Both
        # tolerate no kwargs for a quiet scan.
        return tinytuya.deviceScan(verbose=False, scantime=scantime) or {}
    except Exception:
        # A bound-port collision or a transient ENETUNREACH would otherwise
        # blow up the config flow; swallow and let the UI fall back to
        # manual IP entry.
        return {}


def probe_ip(ip: str, scantime: float = 4.0) -> dict[str, Any] | None:
    """Probe a single LAN IP for a Tuya device and return its scan result,
    or None if the IP isn't a reachable Tuya device within `scantime`.

    Uses tinytuya's `forcescan` in `deviceScan` with the IP filter. Same
    blocking semantics as `lan_scan`.
    """
    try:
        import tinytuya
    except ImportError:
        return None
    try:
        results = (
            tinytuya.deviceScan(
                verbose=False, scantime=scantime, forcescan=[ip],
            )
            or {}
        )
    except Exception:
        return None
    for data in results.values():
        if isinstance(data, dict) and data.get("ip") == ip:
            return data
    return None


def parse_daily_counter(raw: Any) -> int | None:
    """DP 109 is `"N|N|N"` on every firmware we've seen. First segment is
    today's portion total; rest are TBD (week/month guess). Returns None
    on any shape we don't recognize so sensors fall back to unknown rather
    than surfacing garbage.
    """
    if not isinstance(raw, str) or "|" not in raw:
        return None
    head = raw.split("|", 1)[0].strip()
    if not head or not head.lstrip("-").isdigit():
        return None
    try:
        return int(head)
    except ValueError:
        return None


def parse_feed_event(raw: Any) -> dict[str, Any] | None:
    """DP 247/237 normalize: JSON string / dict → `{"portions": N, "time": unix}`.

    Returns None when the raw value is missing or malformed. The device
    occasionally emits `0`, `""`, or partial dicts during boot — we treat
    those as "no event" rather than letting entities render garbage.
    """
    if not raw or raw == 0 or raw == "0":
        return None
    try:
        if isinstance(raw, str):
            obj = json.loads(raw)
        elif isinstance(raw, dict):
            obj = raw
        else:
            return None
    except (ValueError, TypeError):
        return None
    t = obj.get("time")
    if not isinstance(t, (int, float)) or t <= 0:
        return None
    return {"portions": int(obj.get("value") or 0), "time": int(t)}

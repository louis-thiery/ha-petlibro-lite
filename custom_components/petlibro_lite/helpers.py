"""Pure-Python helpers that don't depend on Home Assistant.

Keeping these out of `coordinator.py` lets the unit test suite run without
installing `homeassistant`.
"""

from __future__ import annotations

import json
import logging
from typing import Any


_LOGGER = logging.getLogger(__name__)


def _normalize_scan(raw: Any) -> dict[str, dict[str, Any]]:
    """Flatten tinytuya's `deviceScan()` output (keyed by IP) into a
    `{devId: {"ip": ..., "version": ..., ...}}` mapping so callers can
    look up devices by the identifier that config entries actually use.
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        dev_id = entry.get("gwId") or entry.get("id")
        if not dev_id:
            continue
        out[dev_id] = entry
    return out


def lan_scan(forcescan: bool = False) -> dict[str, dict[str, Any]]:
    """Run tinytuya's LAN discovery and return a mapping
    `{devId: {"ip": str, "version": str, ...}}`.

    Blocking — call via `hass.async_add_executor_job` from async contexts.

    Passive mode (default) listens for Tuya heartbeat UDP broadcasts.
    Forced mode sets `forcescan=True` which adds an active TCP probe of
    each subnet the host is attached to — catches devices whose
    broadcasts don't reach the host (common on HAOS VMs and
    multi-subnet networks). Forced mode is slower (~30s).
    """
    try:
        import tinytuya
    except ImportError:
        _LOGGER.debug("tinytuya not installed — skipping LAN scan")
        return {}
    try:
        raw = tinytuya.deviceScan(verbose=False, forcescan=forcescan)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("tinytuya.deviceScan raised: %s", err)
        return {}
    return _normalize_scan(raw)


def probe_ip(ip: str) -> dict[str, Any] | None:
    """Try to locate a Tuya device at `ip`. Returns its scan entry
    (`{"ip": ..., "gwId": ..., "version": ..., ...}`) or None.

    Strategy: run a normal passive scan first — often enough because a
    target you know the IP of is typically alive and broadcasting. If
    passive finds nothing for that IP, escalate to `forcescan=True`
    which actively probes subnets and tends to hit devices broadcast
    can't reach.
    """
    for forced in (False, True):
        scan = lan_scan(forcescan=forced)
        for entry in scan.values():
            if entry.get("ip") == ip:
                return entry
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

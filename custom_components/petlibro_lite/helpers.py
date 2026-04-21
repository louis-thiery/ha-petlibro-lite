"""Pure-Python helpers that don't depend on Home Assistant.

Keeping these out of `coordinator.py` lets the unit test suite run without
installing `homeassistant`.
"""

from __future__ import annotations

import json
from typing import Any


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

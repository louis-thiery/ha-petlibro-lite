"""Diagnostics export for the PetLibro Lite integration.

Triggered from the HA device page "Download diagnostics" button. Returns
a redacted snapshot users can attach to bug reports without leaking
credentials.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Fields to scrub from the config entry snapshot. localKey is the LAN
# session secret, everything else is a cloud / video credential.
_REDACT_KEYS = {
    "local_key",
    "cloud_password",
    "cloud_sid",
    "cloud_ecode",
    "cloud_uid",
    "cloud_email",
    "p2p_admin_hash",
}


def _state_as_dict(state: Any) -> dict[str, Any] | None:
    """Serialize PetLibroState in a way HA's diagnostics renderer won't
    choke on. Raw DPs are kept so we can see exactly what the feeder
    sent on the last poll — high-value for debugging firmware-quirk
    reports."""
    if state is None:
        return None
    try:
        data = asdict(state)
    except TypeError:
        # Dataclass contains a non-serializable field; fall back to repr.
        return {"repr": repr(state)}
    # schedules contains ScheduleSlot dataclasses (already dict-ified by
    # asdict); nothing else needs post-processing.
    return data


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry,
) -> dict[str, Any]:
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    has_cloud = getattr(runtime, "cloud", None) is not None
    has_stream = getattr(runtime, "stream", None) is not None

    lan_state = None
    lan_last_updated = None
    if runtime is not None and getattr(runtime, "lan", None) is not None:
        lan_state = _state_as_dict(runtime.lan.data)
        lan_last_updated = (
            runtime.lan.last_update_success_time.isoformat()
            if runtime.lan.last_update_success_time
            else None
        )

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), _REDACT_KEYS),
            "options": async_redact_data(dict(entry.options), _REDACT_KEYS),
            "title": entry.title,
            "version": entry.version,
        },
        "runtime": {
            "has_cloud": has_cloud,
            "has_stream": has_stream,
            "lan_last_updated": lan_last_updated,
        },
        "lan_state": lan_state,
    }

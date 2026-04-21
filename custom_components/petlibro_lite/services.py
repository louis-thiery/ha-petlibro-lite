"""Service handlers for schedule editing.

We expose a small surface — `feed`, `schedule_add`, `schedule_update`,
`schedule_remove`, and `schedule_set_all` — and let HA automations compose
them. The device stores schedules as a single blob, so every write goes
through the coordinator, which re-encodes and pushes the full list.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import replace
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import CONF_DEVICE_ID, DOMAIN, MAX_PORTIONS, MAX_SCHEDULE_SLOTS, MIN_PORTIONS
from .coordinator import PetLibroCoordinator
from .schedule import DAYS_LSB_TO_MSB, ScheduleSlot

_LOGGER = logging.getLogger(__name__)

VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
ALL_DAYS_LIST = sorted(VALID_DAYS)

SERVICE_FEED = "feed"
SERVICE_SCHEDULE_ADD = "schedule_add"
SERVICE_SCHEDULE_UPDATE = "schedule_update"
SERVICE_SCHEDULE_REMOVE = "schedule_remove"
SERVICE_SCHEDULE_SET_ALL = "schedule_set_all"
SERVICE_REFRESH_STATE = "refresh_state"

# --- schemas -----------------------------------------------------------------

_SLOT_SCHEMA = vol.Schema(
    {
        vol.Required("hour"): vol.All(int, vol.Range(min=0, max=23)),
        vol.Required("minute"): vol.All(int, vol.Range(min=0, max=59)),
        vol.Required("portions"): vol.All(
            int, vol.Range(min=MIN_PORTIONS, max=MAX_PORTIONS)
        ),
        vol.Required("enabled"): cv.boolean,
        vol.Required("days"): vol.All(
            cv.ensure_list, [vol.In(VALID_DAYS)], vol.Length(min=1)
        ),
    }
)

_DEVICE_SCHEMA = vol.Schema(
    {vol.Required(CONF_DEVICE_ID): str},
    extra=vol.ALLOW_EXTRA,
)

_FEED_SCHEMA = _DEVICE_SCHEMA.extend(
    {
        vol.Required("portions"): vol.All(
            int, vol.Range(min=MIN_PORTIONS, max=MAX_PORTIONS)
        )
    }
)

_SCHEDULE_ADD_SCHEMA = _DEVICE_SCHEMA.extend(_SLOT_SCHEMA.schema)

_SCHEDULE_UPDATE_SCHEMA = _DEVICE_SCHEMA.extend(
    {
        vol.Required("index"): vol.All(int, vol.Range(min=0)),
        # All slot fields optional on update — we patch whatever is provided.
        vol.Optional("hour"): vol.All(int, vol.Range(min=0, max=23)),
        vol.Optional("minute"): vol.All(int, vol.Range(min=0, max=59)),
        vol.Optional("portions"): vol.All(
            int, vol.Range(min=MIN_PORTIONS, max=MAX_PORTIONS)
        ),
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("days"): vol.All(
            cv.ensure_list, [vol.In(VALID_DAYS)], vol.Length(min=1)
        ),
    }
)

_SCHEDULE_REMOVE_SCHEMA = _DEVICE_SCHEMA.extend(
    {vol.Required("index"): vol.All(int, vol.Range(min=0))}
)

_SCHEDULE_SET_ALL_SCHEMA = _DEVICE_SCHEMA.extend(
    {vol.Required("slots"): vol.All(cv.ensure_list, [_SLOT_SCHEMA])}
)


# --- coordinator lookup -------------------------------------------------------


def _resolve_tuya_devid(hass: HomeAssistant, device_id: str) -> str:
    """Map an input device_id (HA-registry UUID or Tuya devId) to the Tuya devId.

    The services.yaml schema now uses `selector: device: integration:
    petlibro_lite`, so callers hand us HA's device registry UUIDs. But
    older automations (from the pre-selector era) may still pass the
    raw Tuya devId — accept both so existing scripts keep working.
    """
    dev_reg = dr.async_get(hass)
    entry = dev_reg.async_get(device_id)
    if entry is not None:
        for iid in entry.identifiers:
            if iid[0] == DOMAIN:
                return iid[1]
    # Not a known HA device UUID — assume it's already a Tuya devId. The
    # downstream coordinator lookup will raise a specific error if it's
    # neither, which is clearer than us surfacing "device not found" for
    # what is actually a naming mismatch.
    return device_id


def _find_coordinator(hass: HomeAssistant, device_id: str) -> PetLibroCoordinator:
    tuya_devid = _resolve_tuya_devid(hass, device_id)
    for runtime in hass.data.get(DOMAIN, {}).values():
        # Internal marker flags (keys starting with "_") live alongside the
        # real PetLibroRuntime instances — skip them to avoid AttributeError.
        if not hasattr(runtime, "lan"):
            continue
        if runtime.lan.client._device_id == tuya_devid:
            return runtime.lan
    raise HomeAssistantError(
        f"no PetLibro device configured with device_id={device_id!r}"
    )


# --- handlers -----------------------------------------------------------------


async def _handle_feed(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = _find_coordinator(hass, call.data[CONF_DEVICE_ID])
    await coord.async_feed(call.data["portions"])


async def _handle_schedule_add(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = _find_coordinator(hass, call.data[CONF_DEVICE_ID])
    slots = list(coord.data.schedules)
    if len(slots) >= MAX_SCHEDULE_SLOTS:
        raise HomeAssistantError(
            f"cannot add: already at maximum of {MAX_SCHEDULE_SLOTS} slots"
        )
    slots.append(_slot_from_call(call.data))
    await coord.async_write_schedules(slots)


async def _handle_schedule_update(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = _find_coordinator(hass, call.data[CONF_DEVICE_ID])
    slots = list(coord.data.schedules)
    idx = call.data["index"]
    if not 0 <= idx < len(slots):
        raise HomeAssistantError(
            f"schedule index {idx} out of range (have {len(slots)} slots)"
        )
    patched_fields: dict[str, Any] = {}
    for key in ("hour", "minute", "portions", "enabled", "days"):
        if key in call.data:
            patched_fields[key] = call.data[key]
    slots[idx] = replace(slots[idx], **patched_fields)
    await coord.async_write_schedules(slots)


async def _handle_schedule_remove(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = _find_coordinator(hass, call.data[CONF_DEVICE_ID])
    slots = list(coord.data.schedules)
    idx = call.data["index"]
    if not 0 <= idx < len(slots):
        raise HomeAssistantError(
            f"schedule index {idx} out of range (have {len(slots)} slots)"
        )
    slots.pop(idx)
    await coord.async_write_schedules(slots)


async def _handle_schedule_set_all(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = _find_coordinator(hass, call.data[CONF_DEVICE_ID])
    slots = [_slot_from_call(s) for s in call.data["slots"]]
    await coord.async_write_schedules(slots)


async def _handle_refresh_state(hass: HomeAssistant, call: ServiceCall) -> None:
    """Force an immediate LAN state poll (DP status).

    Used by the dashboard when the user opens the schedules dialog —
    catches any edits made on the PetLibro app side in the last 10s before
    the card shows the list. Bypasses the coordinator's debouncer so the
    user sees the freshest state without waiting.
    """
    device_id = call.data.get(CONF_DEVICE_ID)
    if device_id:
        coord = _find_coordinator(hass, device_id)
        await coord.async_refresh()
        return
    for runtime in hass.data.get(DOMAIN, {}).values():
        if hasattr(runtime, "lan"):
            await runtime.lan.async_refresh()


def _slot_from_call(data: dict[str, Any]) -> ScheduleSlot:
    return ScheduleSlot(
        hour=data["hour"],
        minute=data["minute"],
        portions=data["portions"],
        enabled=data["enabled"],
        days=[d.lower() for d in data["days"]],
    )


# --- registration -------------------------------------------------------------


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_FEED):
        return  # already registered (multiple config entries share services)

    # HA awaits the registered coroutine directly — no task wrapping needed.
    # Using functools.partial lets the handlers stay free functions that take
    # `hass` as their first argument, which keeps them unit-testable.
    hass.services.async_register(
        DOMAIN,
        SERVICE_FEED,
        functools.partial(_handle_feed, hass),
        schema=_FEED_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCHEDULE_ADD,
        functools.partial(_handle_schedule_add, hass),
        schema=_SCHEDULE_ADD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCHEDULE_UPDATE,
        functools.partial(_handle_schedule_update, hass),
        schema=_SCHEDULE_UPDATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCHEDULE_REMOVE,
        functools.partial(_handle_schedule_remove, hass),
        schema=_SCHEDULE_REMOVE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCHEDULE_SET_ALL,
        functools.partial(_handle_schedule_set_all, hass),
        schema=_SCHEDULE_SET_ALL_SCHEMA,
    )
    # refresh_state: device_id is OPTIONAL — when absent, refresh every
    # configured feeder. Lets dashboards call the service generically.
    _REFRESH_STATE_SCHEMA = vol.Schema(
        {vol.Optional(CONF_DEVICE_ID): str}, extra=vol.ALLOW_EXTRA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_STATE,
        functools.partial(_handle_refresh_state, hass),
        schema=_REFRESH_STATE_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_FEED,
        SERVICE_SCHEDULE_ADD,
        SERVICE_SCHEDULE_UPDATE,
        SERVICE_SCHEDULE_REMOVE,
        SERVICE_SCHEDULE_SET_ALL,
        SERVICE_REFRESH_STATE,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)

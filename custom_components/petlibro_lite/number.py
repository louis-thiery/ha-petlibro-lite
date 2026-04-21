"""PetLibro number platform — feed portions (write-only DP 232)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN, MAX_PORTIONS, MIN_PORTIONS
from .coordinator import PetLibroCoordinator
from .entity import PetLibroEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PetLibroCoordinator = hass.data[DOMAIN][entry.entry_id].lan
    async_add_entities([FeedPortionsNumber(coordinator, entry.data[CONF_DEVICE_ID])])


class FeedPortionsNumber(PetLibroEntity, NumberEntity):
    """Set a value to dispense that many portions.

    DP 232 is write-only; the device never reports it in status. We expose this
    as a NumberEntity with mode=BOX so the HA UI presents a numeric input
    rather than a slider (a slider implies a steady state, but this DP is
    fire-once). We don't expose `native_value` because there's nothing to
    report.
    """

    _attr_translation_key = "feed_portions"
    _attr_name = "Feed portions"
    _attr_icon = "mdi:food-drumstick"
    _attr_native_min_value = MIN_PORTIONS
    _attr_native_max_value = MAX_PORTIONS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: PetLibroCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_feed_portions"

    @property
    def native_value(self) -> float | None:
        # Always None — DP 232 has no persistent state. Returning anything else
        # would be a lie.
        return None

    async def async_set_native_value(self, value: float) -> None:
        portions = int(value)
        if not MIN_PORTIONS <= portions <= MAX_PORTIONS:
            raise ValueError(
                f"portions must be between {MIN_PORTIONS} and {MAX_PORTIONS}"
            )
        await self.coordinator.async_feed(portions)

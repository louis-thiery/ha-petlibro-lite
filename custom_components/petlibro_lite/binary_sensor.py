"""PetLibro binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import PetLibroCoordinator
from .entity import PetLibroEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PetLibroCoordinator = hass.data[DOMAIN][entry.entry_id].lan
    device_id = entry.data[CONF_DEVICE_ID]
    async_add_entities([FeedingPlanActiveSensor(coordinator, device_id)])


class FeedingPlanActiveSensor(PetLibroEntity, BinarySensorEntity):
    """True iff any slot in the schedule list is enabled.

    Mirrors the PetLibro Lite app's "Feeding Plan" master toggle, which
    the device doesn't actually expose as its own DP — the app derives
    this from the schedule list in the same way.
    """

    _attr_translation_key = "feeding_plan_active"
    _attr_name = "Feeding plan active"
    _attr_icon = "mdi:calendar-check"

    def __init__(
        self, coordinator: PetLibroCoordinator, device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_feeding_plan_active"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return any(s.enabled for s in data.schedules)

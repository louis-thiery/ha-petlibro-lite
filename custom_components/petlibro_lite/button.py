"""PetLibro button platform — one-tap feed shortcuts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import PetLibroCoordinator
from .entity import PetLibroEntity


@dataclass(frozen=True, kw_only=True)
class PetLibroButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[PetLibroCoordinator], "asyncio.Future"]


BUTTON_TYPES: tuple[PetLibroButtonDescription, ...] = (
    PetLibroButtonDescription(
        key="feed_1",
        translation_key="feed_1",
        name="Feed 1 portion",
        icon="mdi:food-drumstick",
        press_fn=lambda c: c.async_feed(1),
    ),
    PetLibroButtonDescription(
        key="feed_2",
        translation_key="feed_2",
        name="Feed 2 portions",
        icon="mdi:food-drumstick",
        press_fn=lambda c: c.async_feed(2),
    ),
    PetLibroButtonDescription(
        key="feed_3",
        translation_key="feed_3",
        name="Feed 3 portions",
        icon="mdi:food-drumstick",
        press_fn=lambda c: c.async_feed(3),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PetLibroCoordinator = hass.data[DOMAIN][entry.entry_id].lan
    device_id = entry.data[CONF_DEVICE_ID]
    async_add_entities(
        PetLibroButton(coordinator, device_id, desc) for desc in BUTTON_TYPES
    )


class PetLibroButton(PetLibroEntity, ButtonEntity):
    entity_description: PetLibroButtonDescription

    def __init__(
        self,
        coordinator: PetLibroCoordinator,
        device_id: str,
        description: PetLibroButtonDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)

"""PetLibro switch platform — master switch + per-slot schedule enable."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import PetLibroCoordinator, PetLibroState
from .entity import PetLibroEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PetLibroCoordinator = hass.data[DOMAIN][entry.entry_id].lan
    device_id = entry.data[CONF_DEVICE_ID]

    # Static switches
    async_add_entities([MasterSwitch(coordinator, device_id)])

    # Per-slot switches: add/remove dynamically as the schedule list grows or
    # shrinks. We key by position (0-indexed) because the device itself has no
    # stable slot identifier. Entities for slots that disappear become
    # unavailable rather than being fully removed — HA will expose them again
    # if the list grows back.
    known_positions: set[int] = set()

    @callback
    def _sync_slot_entities() -> None:
        state: PetLibroState = coordinator.data
        if state is None:
            return
        to_add: list[SchedSlotSwitch] = []
        for i in range(len(state.schedules)):
            if i not in known_positions:
                known_positions.add(i)
                to_add.append(SchedSlotSwitch(coordinator, device_id, i))
        if to_add:
            async_add_entities(to_add)

    _sync_slot_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_slot_entities))


class MasterSwitch(PetLibroEntity, SwitchEntity):
    """DP 101 — device master power."""

    _attr_translation_key = "master"
    _attr_name = "Master"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: PetLibroCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_master"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.master_on

    async def async_turn_on(self, **_: object) -> None:
        await self.coordinator.async_set_master(True)

    async def async_turn_off(self, **_: object) -> None:
        await self.coordinator.async_set_master(False)


class SchedSlotSwitch(PetLibroEntity, SwitchEntity):
    """One switch per schedule slot — toggles the `enabled` flag on that slot.

    We encode the whole DP 231 blob on each write since the device accepts only
    the full list (no incremental update protocol). The coordinator's next
    refresh will surface whatever the device decides to persist.
    """

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self, coordinator: PetLibroCoordinator, device_id: str, position: int
    ) -> None:
        super().__init__(coordinator, device_id)
        self._position = position
        self._attr_unique_id = f"{device_id}_schedule_{position}"
        # Name is derived dynamically so editing the slot's time in the app is
        # reflected in the switch label without a HA restart.
        self._attr_translation_key = None

    @property
    def _slot(self):
        slots = self.coordinator.data.schedules
        return slots[self._position] if self._position < len(slots) else None

    @property
    def name(self) -> str | None:
        s = self._slot
        if s is None:
            return f"Schedule {self._position + 1}"
        return f"Schedule {s.hour:02d}:{s.minute:02d} · {s.portions}p"

    @property
    def available(self) -> bool:
        return self._slot is not None and super().available

    @property
    def is_on(self) -> bool | None:
        s = self._slot
        return None if s is None else s.enabled

    async def _async_write_enabled(self, enabled: bool) -> None:
        slots = list(self.coordinator.data.schedules)
        if self._position >= len(slots):
            return
        slots[self._position] = replace(slots[self._position], enabled=enabled)
        await self.coordinator.async_write_schedules(slots)

    async def async_turn_on(self, **_: object) -> None:
        await self._async_write_enabled(True)

    async def async_turn_off(self, **_: object) -> None:
        await self._async_write_enabled(False)

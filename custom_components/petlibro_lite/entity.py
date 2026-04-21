"""Shared base entity for the PetLibro integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PetLibroCoordinator


class PetLibroEntity(CoordinatorEntity[PetLibroCoordinator]):
    """All PetLibro entities attach to the same device registry node."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PetLibroCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        # `serial_number` surfaces the Tuya devId in the HA device-page
        # header ("Serial: ebf6…"), which is what users reference when
        # filing bug reports. Our integration's devId is the closest
        # thing to a serial — feeders don't expose a separate SN over
        # LAN Tuya.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="PetLibro",
            model="PLAF203",
            name=f"PetLibro {device_id[-6:]}",
            serial_number=device_id,
        )

    @property
    def available(self) -> bool:
        """Stay available as long as we've received data at least once.

        The default CoordinatorEntity.available flips to False the instant any
        single poll fails. For a LAN Tuya device that's a lot of transient
        blips (WiFi retransmits, feeder briefly unreachable, HA restart), and
        every flip writes a spurious state-change row to the recorder — which
        is what produces "phantom feed events" in feed history views.

        Instead, hold the last-known value indefinitely once the coordinator
        has succeeded at least once. Pets don't care whether the *network
        path* is healthy, only whether the last known feed info is correct.
        """
        return self.coordinator.data is not None

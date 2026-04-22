"""Camera platform for the PetLibro feeder video feed.

Standard feature of the integration — every feeder gets a camera
entity. The feed is the feeder's live HEVC stream via Home Assistant's
Stream component; HA transcodes the integration-provided HLS playlist
and serves the browser an hls.js/<video> source.

The only time camera registration is skipped is when the config entry
is missing a cloud session (legacy entries where the session expired
before the admin-hash backfill could run; fixed by running the
reconfigure flow).

Stream lifecycle is managed by `PetLibroStreamManager` on-demand: the
upstream RTC+KCP session only runs while a viewer is actively pulling
the playlist.
"""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PetLibroRuntime
from .const import CONF_DEVICE_ID, DOMAIN
from .entity import PetLibroEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PetLibroRuntime = hass.data[DOMAIN][entry.entry_id]
    if runtime.stream is None:
        # Cloud session missing — see module docstring for recovery.
        return
    async_add_entities([PetLibroCamera(runtime, entry)])


class PetLibroCamera(PetLibroEntity, Camera):
    """Feeder live video feed backed by on-demand KCP→HLS pipeline."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_icon = "mdi:cctv"

    def __init__(self, runtime: PetLibroRuntime, entry: ConfigEntry) -> None:
        PetLibroEntity.__init__(
            self, runtime.lan, entry.data[CONF_DEVICE_ID],
        )
        Camera.__init__(self)
        self._runtime = runtime
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_camera"
        self._unsub_phase: callable | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Subscribe to the stream manager's phase transitions so the
        # `stream_state` attribute updates in real time (signaling →
        # ice → auth → waiting_frame → streaming). Cards drive their
        # "Connecting…" overlay off this without polling.
        manager = self._runtime.stream
        if manager is not None:
            self._unsub_phase = manager.add_phase_listener(
                lambda _p: self.async_write_ha_state()
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_phase is not None:
            self._unsub_phase()
            self._unsub_phase = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._runtime.stream
        if manager is None:
            return {}
        return {"stream_state": manager.phase}

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None,
    ) -> bytes | None:
        manager = self._runtime.stream
        if manager is None:
            return None
        try:
            return await manager.async_get_snapshot()
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("snapshot failed: %s", e)
            return None

    async def stream_source(self) -> str | None:
        manager = self._runtime.stream
        if manager is None:
            return None
        await manager.async_ensure_running()
        return manager.hls_url()

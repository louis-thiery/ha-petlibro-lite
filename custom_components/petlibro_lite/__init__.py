"""The PetLibro Lite integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .config_flow import async_fetch_admin_hash
from .const import (
    CONF_CLOUD_ECODE,
    CONF_CLOUD_SID,
    CONF_CLOUD_UID,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_P2P_ADMIN_HASH,
    CONF_P2P_ADMIN_USER,
    CONF_PROTOCOL,
    DEFAULT_P2P_ADMIN_USER,
    DOMAIN,
)
from .coordinator import PetLibroCoordinator
from .services import async_register_services, async_unregister_services
from .tuya_client import TuyaClient
from .video.driver import StreamParams
from .video.http import PetLibroStreamView
from .video.stream_manager import PetLibroStreamManager

_LOGGER = logging.getLogger(__name__)

BASE_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class PetLibroRuntime:
    """Per-entry runtime state shared with platforms + services."""

    lan: PetLibroCoordinator
    stream: PetLibroStreamManager | None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not entry.data.get(CONF_P2P_ADMIN_HASH) and entry.data.get(CONF_CLOUD_SID):
        hass.async_create_task(_try_populate_admin_hash(hass, entry))

    client = TuyaClient(
        device_id=entry.data[CONF_DEVICE_ID],
        local_key=entry.data[CONF_LOCAL_KEY],
        host=entry.data[CONF_HOST],
        protocol=entry.data[CONF_PROTOCOL],
    )
    lan = PetLibroCoordinator(
        hass, client,
        name=entry.title or entry.data[CONF_DEVICE_ID],
        device_id=entry.data[CONF_DEVICE_ID],
    )
    await lan.async_config_entry_first_refresh()

    stream = _build_stream_manager(hass, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = PetLibroRuntime(
        lan=lan, stream=stream,
    )

    # Register the HLS HTTP view + Lovelace-card static path once (first
    # entry); subsequent entries reuse them because HLS dispatches on the
    # `entry_id` URL path param and the card file is shared.
    if not hass.data[DOMAIN].get("_http_view_registered"):
        hass.http.register_view(PetLibroStreamView(hass))
        card_dir = Path(__file__).parent / "www"
        if card_dir.exists():
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/petlibro_lite_static",
                        str(card_dir),
                        cache_headers=True,
                    ),
                ]
            )
        hass.data[DOMAIN]["_http_view_registered"] = True

    platforms = list(BASE_PLATFORMS)
    if stream is not None:
        platforms.append(Platform.CAMERA)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    async_register_services(hass)
    return True


async def _try_populate_admin_hash(
    hass: HomeAssistant, entry: ConfigEntry,
) -> None:
    """Best-effort admin-hash backfill for legacy entries.

    Existing entries from before the integration auto-derived the hash
    have the cloud session and localKey stored, but no `p2p_admin_hash`.
    Derive one asynchronously and reload the entry so the camera
    platform registers without requiring a second HA restart.
    """
    admin_hash = await async_fetch_admin_hash(
        hass,
        entry.data[CONF_CLOUD_SID],
        entry.data[CONF_CLOUD_ECODE],
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_LOCAL_KEY],
        "backfill on startup",
    )
    if not admin_hash:
        return

    new_data = dict(entry.data)
    new_data[CONF_P2P_ADMIN_USER] = DEFAULT_P2P_ADMIN_USER
    new_data[CONF_P2P_ADMIN_HASH] = admin_hash
    hass.config_entries.async_update_entry(entry, data=new_data)
    _LOGGER.info("admin-hash backfilled from cloud for %s", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


def _build_stream_manager(
    hass: HomeAssistant, entry: ConfigEntry,
) -> PetLibroStreamManager | None:
    """Construct the on-demand video stream manager.

    Camera entity is part of the integration's standard feature set —
    it's only skipped when the cloud session is unavailable (e.g. an
    expired session on a legacy entry where the user hasn't run the
    reconfigure flow yet).
    """
    admin_hash = entry.data.get(CONF_P2P_ADMIN_HASH)
    sid = entry.data.get(CONF_CLOUD_SID)
    ecode = entry.data.get(CONF_CLOUD_ECODE)
    uid = entry.data.get(CONF_CLOUD_UID)
    if not (admin_hash and sid and ecode and uid):
        return None

    local_key = entry.data[CONF_LOCAL_KEY]
    if len(local_key.encode("utf-8")) != 16:
        _LOGGER.warning(
            "petlibro_lite video: localKey is %d bytes, need 16 — camera disabled",
            len(local_key.encode("utf-8")),
        )
        return None

    params = StreamParams(
        sid=sid,
        ecode=ecode,
        uid=uid,
        dev_id=entry.data[CONF_DEVICE_ID],
        local_key=local_key.encode("utf-8"),
        admin_user=entry.data.get(CONF_P2P_ADMIN_USER) or DEFAULT_P2P_ADMIN_USER,
        admin_hash=admin_hash,
    )
    return PetLibroStreamManager(hass, entry.entry_id, params)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime: PetLibroRuntime | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    platforms = list(BASE_PLATFORMS)
    if runtime is not None and runtime.stream is not None:
        platforms.append(Platform.CAMERA)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        if runtime is not None and runtime.stream is not None:
            await runtime.stream.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Drop the view-registered marker only when the last entry unloads,
        # so a re-setup after a complete unload doesn't leak a duplicate route.
        if not any(
            k for k in hass.data[DOMAIN] if k != "_http_view_registered"
        ):
            hass.data[DOMAIN].pop("_http_view_registered", None)
            if not hass.data[DOMAIN]:
                async_unregister_services(hass)
    return unload_ok

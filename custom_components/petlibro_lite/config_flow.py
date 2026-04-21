"""UI config flow for the PetLibro Lite integration.

Two-step flow:

  1. Device credentials (required): the local-LAN quad of devId, localKey,
     IP, and protocol version. This is enough to get every feature working
     except live video. LAN-only is the first-class operating mode.

  2. Video credentials (optional, video-only): PetLibro account email +
     password and P2P admin hash. These are exchanged for a Tuya session
     that the WebRTC handshake requires and fed into the video platform.
     Skip this step entirely to run the integration without video — every
     non-video sensor, switch, button, and schedule feature works fine
     without it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .cloud import TuyaApiClient
from .cloud.login import login as cloud_login
from .const import (
    CONF_CLOUD_COUNTRY_CODE,
    CONF_CLOUD_ECODE,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_SID,
    CONF_CLOUD_UID,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_P2P_ADMIN_HASH,
    CONF_P2P_ADMIN_USER,
    CONF_PROTOCOL,
    DEFAULT_CLOUD_COUNTRY,
    DEFAULT_P2P_ADMIN_USER,
    DEFAULT_PROTOCOL,
    DOMAIN,
)
from .tuya_client import TuyaClient, TuyaClientError

_LOGGER = logging.getLogger(__name__)

PROTOCOL_OPTIONS = ["3.1", "3.2", "3.3", "3.4"]

# Tuya server returns errors like `{... 'errorMsg': 'Incorrect account or password'}`.
# `login()` re-raises that dict inside a RuntimeError, so we pluck the message back
# out here to show in the form rather than a generic "rejected" label.
_ERRMSG_RE = re.compile(r"'errorMsg':\s*'([^']+)'")


def _extract_reason(err: Exception) -> str:
    """Best-effort: pull the Tuya server's errorMsg out of a login exception."""
    m = _ERRMSG_RE.search(str(err))
    if m:
        return m.group(1)
    # Fallback: show type + short repr for non-Tuya failures (timeouts,
    # DNS errors, pycryptodome missing, etc.).
    return f"{type(err).__name__}: {err}"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): vol.In(PROTOCOL_OPTIONS),
    }
)

# Video setup bundles everything needed for the camera platform — leaving
# every field blank is the common case and the integration simply runs
# without video.
STEP_VIDEO_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CLOUD_EMAIL, default=""): str,
        vol.Optional(CONF_CLOUD_PASSWORD, default=""): str,
        vol.Optional(
            CONF_CLOUD_COUNTRY_CODE, default=DEFAULT_CLOUD_COUNTRY
        ): str,
        vol.Optional(CONF_P2P_ADMIN_USER, default=DEFAULT_P2P_ADMIN_USER): str,
        vol.Optional(CONF_P2P_ADMIN_HASH, default=""): str,
    }
)


class PetLibroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the device-credentials config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._lan_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PetLibroOptionsFlow:
        """Expose the "Configure" button on an existing entry so the user
        can add/remove cloud credentials without deleting and re-creating
        the integration."""
        return PetLibroOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            client = TuyaClient(
                device_id=user_input[CONF_DEVICE_ID],
                local_key=user_input[CONF_LOCAL_KEY],
                host=user_input[CONF_HOST],
                protocol=user_input[CONF_PROTOCOL],
            )
            try:
                await client.status()
            except TuyaClientError as err:
                _LOGGER.debug("connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._lan_data = dict(user_input)
                return await self.async_step_video()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_video(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional video setup. Cloud email+password is exchanged for a
        Tuya session (needed for the WebRTC offer), and the P2P admin
        hash authorizes the P2P stream. Any of these blank → no video,
        integration still runs fully without a camera."""
        errors: dict[str, str] = {}
        reason: str = ""

        if user_input is not None:
            email = (user_input.get(CONF_CLOUD_EMAIL) or "").strip()
            password = user_input.get(CONF_CLOUD_PASSWORD) or ""
            country = (
                user_input.get(CONF_CLOUD_COUNTRY_CODE) or DEFAULT_CLOUD_COUNTRY
            ).strip() or DEFAULT_CLOUD_COUNTRY
            p2p_user_in = (user_input.get(CONF_P2P_ADMIN_USER) or "").strip()
            p2p_hash_in = (user_input.get(CONF_P2P_ADMIN_HASH) or "").strip()

            data = dict(self._lan_data)
            if p2p_hash_in:
                data[CONF_P2P_ADMIN_USER] = p2p_user_in or DEFAULT_P2P_ADMIN_USER
                data[CONF_P2P_ADMIN_HASH] = p2p_hash_in

            if not email and not password:
                # User skipped video. Fine — integration runs LAN-only.
                return self._create(data)

            if not email or not password:
                errors["base"] = "cloud_incomplete"
            else:
                try:
                    result = await self.hass.async_add_executor_job(
                        _run_login, email, password, country,
                    )
                except Exception as err:  # noqa: BLE001
                    # Surface the real exception — login failures can be caused
                    # by a lot of things (wrong country code, missing RSA lib,
                    # Tuya rate-limit, network issue) and a generic "rejected"
                    # label hides which. WARNING so it shows up in HA core logs
                    # without needing debug level enabled.
                    _LOGGER.warning(
                        "PetLibro cloud login failed: %s: %s",
                        type(err).__name__, err,
                    )
                    reason = _extract_reason(err)
                    # Surface the literal Tuya errorMsg in the form's error
                    # field: HA's frontend falls back to the raw error string
                    # when no translation matches, so e.g. "Incorrect account
                    # or password" renders directly without us needing a
                    # translation key per Tuya error code. Bypasses the
                    # browser-side translation cache issue where a stale
                    # description template wouldn't pick up {reason}.
                    errors["base"] = reason or "cloud_auth"
                else:
                    data.update(
                        {
                            CONF_CLOUD_EMAIL: email,
                            CONF_CLOUD_PASSWORD: password,
                            CONF_CLOUD_COUNTRY_CODE: country,
                            CONF_CLOUD_SID: result["sid"],
                            CONF_CLOUD_ECODE: result["ecode"],
                            CONF_CLOUD_UID: result["uid"],
                        }
                    )
                    return self._create(data)

        return self.async_show_form(
            step_id="video",
            data_schema=STEP_VIDEO_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"reason": reason},
        )

    def _create(self, data: dict[str, Any]) -> FlowResult:
        return self.async_create_entry(
            title=f"PetLibro {data[CONF_DEVICE_ID][-6:]}", data=data,
        )


def _run_login(email: str, password: str, country: str) -> dict[str, str]:
    """Sync helper: instantiate a throwaway client + log in, return session
    tokens the config entry needs to persist."""
    client = TuyaApiClient()
    result = cloud_login(client, email, password, country_code=country)
    return {"sid": result.sid, "ecode": result.ecode, "uid": result.uid}


class PetLibroOptionsFlow(config_entries.OptionsFlow):
    """Reconfigure cloud creds on an already-installed entry. Bounces the
    integration so the new credentials take effect immediately."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        reason: str = ""
        current = self._entry.data

        if user_input is not None:
            email = (user_input.get(CONF_CLOUD_EMAIL) or "").strip()
            password = user_input.get(CONF_CLOUD_PASSWORD) or ""
            country = (
                user_input.get(CONF_CLOUD_COUNTRY_CODE) or DEFAULT_CLOUD_COUNTRY
            ).strip() or DEFAULT_CLOUD_COUNTRY
            p2p_user_in = (user_input.get(CONF_P2P_ADMIN_USER) or "").strip()
            p2p_hash_in = (user_input.get(CONF_P2P_ADMIN_HASH) or "").strip()

            new_data = {**current}
            # Sync P2P admin creds unconditionally — they're independent of
            # the cloud-auth decision below. Empty hash clears video.
            if p2p_hash_in:
                new_data[CONF_P2P_ADMIN_USER] = (
                    p2p_user_in or DEFAULT_P2P_ADMIN_USER
                )
                new_data[CONF_P2P_ADMIN_HASH] = p2p_hash_in
            else:
                new_data.pop(CONF_P2P_ADMIN_USER, None)
                new_data.pop(CONF_P2P_ADMIN_HASH, None)

            if not email and not password:
                # User cleared cloud credentials → turn cloud off. We still
                # write any P2P admin hash changes that were made in the
                # same submission (handled above).
                for k in (
                    CONF_CLOUD_EMAIL,
                    CONF_CLOUD_PASSWORD,
                    CONF_CLOUD_COUNTRY_CODE,
                    CONF_CLOUD_SID,
                    CONF_CLOUD_ECODE,
                    CONF_CLOUD_UID,
                ):
                    new_data.pop(k, None)
                self.hass.config_entries.async_update_entry(
                    self._entry, data=new_data,
                )
                await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_create_entry(title="", data={})

            if not email or not password:
                errors["base"] = "cloud_incomplete"
            else:
                try:
                    result = await self.hass.async_add_executor_job(
                        _run_login, email, password, country,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "PetLibro cloud login failed (options): %s: %s",
                        type(err).__name__, err,
                    )
                    reason = _extract_reason(err)
                    errors["base"] = reason or "cloud_auth"
                else:
                    new_data.update(
                        {
                            CONF_CLOUD_EMAIL: email,
                            CONF_CLOUD_PASSWORD: password,
                            CONF_CLOUD_COUNTRY_CODE: country,
                            CONF_CLOUD_SID: result["sid"],
                            CONF_CLOUD_ECODE: result["ecode"],
                            CONF_CLOUD_UID: result["uid"],
                        }
                    )
                    self.hass.config_entries.async_update_entry(
                        self._entry, data=new_data,
                    )
                    await self.hass.config_entries.async_reload(
                        self._entry.entry_id,
                    )
                    return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CLOUD_EMAIL,
                    default=current.get(CONF_CLOUD_EMAIL, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_PASSWORD,
                    default=current.get(CONF_CLOUD_PASSWORD, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_COUNTRY_CODE,
                    default=current.get(
                        CONF_CLOUD_COUNTRY_CODE, DEFAULT_CLOUD_COUNTRY
                    ),
                ): str,
                # Video camera: P2P admin user + per-device hash (Tuya
                # "admin" creds for the binary stream). Leaving hash
                # blank disables the camera platform.
                vol.Optional(
                    CONF_P2P_ADMIN_USER,
                    default=current.get(
                        CONF_P2P_ADMIN_USER, DEFAULT_P2P_ADMIN_USER,
                    ),
                ): str,
                vol.Optional(
                    CONF_P2P_ADMIN_HASH,
                    default=current.get(CONF_P2P_ADMIN_HASH, ""),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"reason": reason},
        )

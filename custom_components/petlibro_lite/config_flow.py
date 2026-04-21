"""UI config flow for the PetLibro Lite integration.

v0.2 auto-setup flow:

  1. `user` step — single form: PetLibro Lite email + password (required) +
     optional LAN IP override. We log in to the cloud, run a tinytuya LAN
     scan, and for every Tuya device found on the LAN we call
     `tuya.m.device.get` with the fresh session to fetch its `localKey`.
     Any device that returns successfully is one the account owns.
  2. `pick` step — shown only if more than one eligible feeder is found
     and more than one is not yet configured in HA.
  3. `video` step — optional. P2P admin user + hash. Leaving blank
     registers no camera platform; every non-video feature works.

For existing users upgrading from the manual-entry flow, the stored
entry shape is unchanged (`device_id`, `local_key`, `host`, `protocol`,
plus the cloud + video fields). A reconfigure flow is also exposed so
existing entries can refresh their cloud session or swap to a different
feeder on the account without deletion.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from types import MappingProxyType

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
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
from .helpers import lan_scan, probe_ip
from .tuya_client import TuyaClient, TuyaClientError

_LOGGER = logging.getLogger(__name__)

_ERRMSG_RE = re.compile(r"'errorMsg':\s*'([^']+)'")


def _extract_reason(err: Exception) -> str:
    """Best-effort: pull the Tuya server's errorMsg out of an exception."""
    m = _ERRMSG_RE.search(str(err))
    if m:
        return m.group(1)
    return f"{type(err).__name__}: {err}"


USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLOUD_EMAIL): str,
        vol.Required(CONF_CLOUD_PASSWORD): str,
        vol.Optional(
            CONF_CLOUD_COUNTRY_CODE, default=DEFAULT_CLOUD_COUNTRY
        ): str,
        # Optional. If set, we'll probe this exact IP instead of broadcast
        # scanning. Useful when UDP discovery is blocked or the feeder is
        # on a different subnet.
        vol.Optional(CONF_HOST, default=""): str,
    }
)

VIDEO_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_P2P_ADMIN_USER, default=DEFAULT_P2P_ADMIN_USER): str,
        vol.Optional(CONF_P2P_ADMIN_HASH, default=""): str,
    }
)


class PetLibroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Auto-discovery config flow for PetLibro Lite."""

    VERSION = 1

    def __init__(self) -> None:
        # Buffers populated across steps:
        #   _cloud_auth: sid/ecode/uid/email/password/country after login
        #   _candidates: list of dicts with merged LAN + cloud info
        #   _selected: dict from _candidates chosen by user (single entry)
        self._cloud_auth: dict[str, Any] = {}
        self._candidates: list[dict[str, Any]] = []
        self._selected: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "PetLibroOptionsFlow":
        return PetLibroOptionsFlow(config_entry)

    # -- Step 1: login + discover -------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        reason = ""

        if user_input is not None:
            email = (user_input.get(CONF_CLOUD_EMAIL) or "").strip()
            password = user_input.get(CONF_CLOUD_PASSWORD) or ""
            country = (
                user_input.get(CONF_CLOUD_COUNTRY_CODE) or DEFAULT_CLOUD_COUNTRY
            ).strip() or DEFAULT_CLOUD_COUNTRY
            manual_ip = (user_input.get(CONF_HOST) or "").strip()

            if not email or not password:
                errors["base"] = "cloud_incomplete"
            else:
                try:
                    auth = await self.hass.async_add_executor_job(
                        _run_login, email, password, country,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "PetLibro cloud login failed: %s: %s",
                        type(err).__name__, err,
                    )
                    reason = _extract_reason(err)
                    errors["base"] = reason or "cloud_auth"
                else:
                    self._cloud_auth = {
                        CONF_CLOUD_EMAIL: email,
                        CONF_CLOUD_PASSWORD: password,
                        CONF_CLOUD_COUNTRY_CODE: country,
                        **auth,
                    }
                    # Discover candidates (LAN scan + per-device cloud lookup).
                    candidates = await self.hass.async_add_executor_job(
                        _discover_candidates,
                        auth["cloud_sid"],
                        auth["cloud_ecode"],
                        manual_ip,
                    )
                    # Filter out already-configured devIds so we don't show
                    # the user a feeder they've already set up.
                    existing = {
                        e.data.get(CONF_DEVICE_ID)
                        for e in self._async_current_entries()
                    }
                    candidates = [
                        c for c in candidates
                        if c[CONF_DEVICE_ID] not in existing
                    ]
                    if not candidates:
                        errors["base"] = "no_devices_found"
                    else:
                        self._candidates = candidates
                        return await self._advance_from_candidates()

        return self.async_show_form(
            step_id="user",
            data_schema=USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"reason": reason},
        )

    async def _advance_from_candidates(self) -> FlowResult:
        """Either go to the pick step (multi-device) or directly to video."""
        if len(self._candidates) == 1:
            self._selected = self._candidates[0]
            await self.async_set_unique_id(self._selected[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            return await self.async_step_video()
        return await self.async_step_pick()

    # -- Step 2: pick (only when multiple feeders) -------------------------

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        options = {
            c[CONF_DEVICE_ID]: f"{c.get('name') or 'feeder'} · {c[CONF_HOST]}"
            for c in self._candidates
        }

        if user_input is not None:
            choice = user_input["choice"]
            self._selected = next(
                c for c in self._candidates if c[CONF_DEVICE_ID] == choice
            )
            await self.async_set_unique_id(self._selected[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            return await self.async_step_video()

        schema = vol.Schema({vol.Required("choice"): vol.In(options)})
        return self.async_show_form(step_id="pick", data_schema=schema)

    # -- Step 3: optional video --------------------------------------------

    async def async_step_video(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            p2p_user = (user_input.get(CONF_P2P_ADMIN_USER) or "").strip()
            p2p_hash = (user_input.get(CONF_P2P_ADMIN_HASH) or "").strip()
            data = self._build_entry_data(p2p_user, p2p_hash)
            # Title is the cloud-returned name when present, else a
            # "PetLibro <last6>" fallback.
            title = self._selected.get("name") or (
                f"PetLibro {self._selected[CONF_DEVICE_ID][-6:]}"
            )
            return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="video", data_schema=VIDEO_DATA_SCHEMA,
        )

    def _build_entry_data(self, p2p_user: str, p2p_hash: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            CONF_DEVICE_ID: self._selected[CONF_DEVICE_ID],
            CONF_LOCAL_KEY: self._selected[CONF_LOCAL_KEY],
            CONF_HOST: self._selected[CONF_HOST],
            CONF_PROTOCOL: self._selected.get(CONF_PROTOCOL, DEFAULT_PROTOCOL),
            **self._cloud_auth,
        }
        if p2p_hash:
            data[CONF_P2P_ADMIN_USER] = p2p_user or DEFAULT_P2P_ADMIN_USER
            data[CONF_P2P_ADMIN_HASH] = p2p_hash
        return data


# -- Helpers -----------------------------------------------------------------


def _run_login(email: str, password: str, country: str) -> dict[str, str]:
    """Sync helper executed via `async_add_executor_job`. Returns the
    session fields we persist on the config entry."""
    client = TuyaApiClient()
    result = cloud_login(client, email, password, country_code=country)
    return {
        CONF_CLOUD_SID: result.sid,
        CONF_CLOUD_ECODE: result.ecode,
        CONF_CLOUD_UID: result.uid,
    }


def _discover_candidates(
    sid: str, ecode: str, manual_ip: str,
) -> list[dict[str, Any]]:
    """Combine LAN scan + per-device cloud lookup into a single list.

    Each returned dict has at minimum:
      device_id, local_key, host, protocol, name (may be '')

    A device makes it into the list iff the cloud session can successfully
    `tuya.m.device.get` it — i.e. it's paired to this user's account.
    """
    results: dict[str, dict[str, Any]] = {}
    if manual_ip:
        probe = probe_ip(manual_ip)
        if probe and probe.get("gwId"):
            results[probe["gwId"]] = probe
    else:
        results = lan_scan()

    if not results:
        return []

    client = TuyaApiClient(sid=sid, ecode=ecode)
    candidates: list[dict[str, Any]] = []
    for dev_id, scan in results.items():
        try:
            meta = client.device_get(dev_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "device_get(%s) skipped — not on this account: %s",
                dev_id, _extract_reason(err),
            )
            continue
        local_key = meta.get("localKey")
        if not local_key:
            continue
        ip = scan.get("ip") or manual_ip
        version = scan.get("version")
        protocol = f"{version:.1f}" if isinstance(version, (int, float)) else DEFAULT_PROTOCOL
        candidates.append(
            {
                CONF_DEVICE_ID: dev_id,
                CONF_LOCAL_KEY: local_key,
                CONF_HOST: ip,
                CONF_PROTOCOL: protocol,
                "name": meta.get("name") or "",
                "product_id": meta.get("productId") or "",
                "mac": meta.get("mac") or "",
            }
        )
    return candidates


# -- Options flow: reconfigure cloud + video credentials --------------------


class PetLibroOptionsFlow(config_entries.OptionsFlow):
    """Options flow for existing entries. Lets users:

    - Refresh the cloud session (re-login, write new sid/ecode/uid).
    - Override the LAN IP if the feeder moved to a different address.
    - Add / update / clear the P2P admin hash (video toggle).
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        reason = ""
        current = self._entry.data

        if user_input is not None:
            email = (user_input.get(CONF_CLOUD_EMAIL) or "").strip()
            password = user_input.get(CONF_CLOUD_PASSWORD) or ""
            country = (
                user_input.get(CONF_CLOUD_COUNTRY_CODE) or DEFAULT_CLOUD_COUNTRY
            ).strip() or DEFAULT_CLOUD_COUNTRY
            host_in = (user_input.get(CONF_HOST) or "").strip()
            p2p_user_in = (user_input.get(CONF_P2P_ADMIN_USER) or "").strip()
            p2p_hash_in = (user_input.get(CONF_P2P_ADMIN_HASH) or "").strip()

            new_data = dict(current)
            if host_in:
                new_data[CONF_HOST] = host_in
            if p2p_hash_in:
                new_data[CONF_P2P_ADMIN_USER] = (
                    p2p_user_in or DEFAULT_P2P_ADMIN_USER
                )
                new_data[CONF_P2P_ADMIN_HASH] = p2p_hash_in
            else:
                # Explicitly clearing the hash turns video off.
                new_data.pop(CONF_P2P_ADMIN_USER, None)
                new_data.pop(CONF_P2P_ADMIN_HASH, None)

            commit = False
            if not email and not password:
                # No new cloud creds — keep existing, just apply non-auth changes.
                commit = True
            elif not email or not password:
                errors["base"] = "cloud_incomplete"
            else:
                try:
                    auth = await self.hass.async_add_executor_job(
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
                            **auth,
                        }
                    )
                    # If entry has a devId, re-pull localKey in case it
                    # rotated (rare, but possible after factory reset +
                    # re-pair).
                    dev_id = new_data.get(CONF_DEVICE_ID)
                    if dev_id:
                        try:
                            client = TuyaApiClient(
                                sid=auth["cloud_sid"],
                                ecode=auth["cloud_ecode"],
                            )
                            meta = await self.hass.async_add_executor_job(
                                client.device_get, dev_id,
                            )
                            if meta.get("localKey"):
                                new_data[CONF_LOCAL_KEY] = meta["localKey"]
                        except Exception as err:  # noqa: BLE001
                            _LOGGER.debug(
                                "localKey refresh skipped: %s",
                                _extract_reason(err),
                            )
                    commit = True

            if commit:
                self.hass.config_entries.async_update_entry(
                    self._entry, data=new_data,
                )
                await self.hass.config_entries.async_reload(
                    self._entry.entry_id,
                )
                return self.async_create_entry(title="", data={})

        # Pre-fill from current data where sensible. Leave the password
        # field empty — users who want to re-auth type it fresh.
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CLOUD_EMAIL,
                    default=current.get(CONF_CLOUD_EMAIL, ""),
                ): str,
                vol.Optional(CONF_CLOUD_PASSWORD, default=""): str,
                vol.Optional(
                    CONF_CLOUD_COUNTRY_CODE,
                    default=current.get(
                        CONF_CLOUD_COUNTRY_CODE, DEFAULT_CLOUD_COUNTRY,
                    ),
                ): str,
                vol.Optional(
                    CONF_HOST, default=current.get(CONF_HOST, ""),
                ): str,
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

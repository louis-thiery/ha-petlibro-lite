"""Thin async wrapper around `tinytuya` for PetLibro/Tuya LAN control.

tinytuya is synchronous and mixes socket I/O with JSON handling. We run every
call in HA's executor so we never block the event loop, and we wrap the raw
responses in a predictable shape so callers never have to worry about the
different forms tinytuya returns (sometimes dict, sometimes None, sometimes
raises).

Writes to action DPs (e.g. 232 feed) echo back the old query shape rather than
the written value; this is a quirk of tinytuya's `set_value`, not the device.
Callers who need the post-write state should poll `status()` afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)


class TuyaClientError(Exception):
    """Raised when a tinytuya call fails in a way we expect callers to handle."""


class TuyaClient:
    def __init__(
        self,
        *,
        device_id: str,
        local_key: str,
        host: str,
        protocol: str = "3.4",
    ) -> None:
        self._device_id = device_id
        self._local_key = local_key
        self._host = host
        self._protocol = protocol
        # Serialize all calls. tinytuya opens a short-lived TCP session per call,
        # but the PLAF203 sometimes struggles with two concurrent sessions (we
        # saw dropped reads during LocalTuya's polling while we also called
        # tinytuya directly). A per-client lock keeps us polite.
        self._lock = asyncio.Lock()
        self._device: tinytuya.OutletDevice | None = None

    def _ensure_device(self) -> tinytuya.OutletDevice:
        if self._device is None:
            self._device = tinytuya.OutletDevice(
                self._device_id,
                self._host,
                self._local_key,
                version=float(self._protocol),
            )
            # Two retries smooths over transient socket hiccups without
            # masking a real outage.
            self._device.set_socketRetryLimit(2)
            # Keep the session alive between polls — saves ~500ms of TCP +
            # session-key negotiation on every 10s cycle, so reads feel
            # snappy and we don't spam the feeder with connect/disconnect
            # churn. Session key rotation + socket re-establishment happen
            # automatically inside tinytuya if the socket goes stale.
            self._device.set_socketPersistent(True)
            # Short read timeout so a hung feeder doesn't wedge the
            # coordinator for a full minute — we surface UpdateFailed
            # quickly and retry on the next poll.
            self._device.set_socketTimeout(5)
        return self._device

    async def _run(self, fn, *args, **kwargs) -> Any:
        async with self._lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: fn(*args, **kwargs)
            )

    async def status(self) -> dict[str, Any]:
        """Return the current DPS map. Raises on unrecoverable errors."""

        def _call() -> dict[str, Any]:
            dev = self._ensure_device()
            resp = dev.status()
            if not isinstance(resp, dict):
                raise TuyaClientError(f"unexpected status response: {resp!r}")
            if "Error" in resp:
                raise TuyaClientError(
                    f"device returned error: {resp.get('Error')!r}"
                )
            return resp.get("dps") or {}

        return await self._run(_call)

    async def set_dp(self, dp: int | str, value: Any) -> None:
        """Write a single DP. Fire-and-forget — caller polls status() to confirm.

        We explicitly return None because tinytuya's response shape for action
        DPs (like 232) is misleading — it echoes the old query value, which
        looks like the write failed when it actually succeeded. Making the API
        return nothing prevents callers from building checks on top of a lie.
        """

        def _call() -> None:
            dev = self._ensure_device()
            dev.set_value(dp, value)

        await self._run(_call)

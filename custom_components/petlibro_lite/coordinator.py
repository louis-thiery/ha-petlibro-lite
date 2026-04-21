"""HA DataUpdateCoordinator for PetLibro.

Polls the device on a fixed interval, fans DP-change transitions out as HA
bus events, and exposes a typed snapshot to entities. Write helpers go
through the coordinator so a write can immediately trigger a refresh — this
keeps HA's displayed state in sync with the device quickly without having
to wait for the next scheduled poll.

Warning state is startup-aware: DP 236 (warning code) on PLAF203 is sticky
— the feeder latches the last warning code indefinitely. Without special
handling, an HA restart re-reports a jam that was physically cleared days
ago. We track DP 236 edges (0 → N transitions) at runtime and only surface
a warning in `PetLibroState.warning` when:

  1. We observed an actual rising edge after the integration started, AND
  2. No successful feed (DP 247/237 timestamp newer than that edge) has
     happened since, AND
  3. The raised edge is younger than ACTIVE_WARN_WINDOW_SEC (1h).

Feed/warning bus events let dashboards and automations react in real
time without any cloud involvement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DP_DAILY_COUNTERS,
    DP_DEVICE_STATE,
    DP_FEED_PORTIONS,
    DP_FOOD_LEVEL,
    DP_LAST_MANUAL_FEED,
    DP_LAST_SCHEDULED_FEED,
    DP_MASTER_SWITCH,
    DP_SCHEDULES,
    DP_WARNING,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_FEED,
    EVENT_WARNING,
    WARNING_LABELS,
)
from .helpers import parse_daily_counter, parse_feed_event
from .schedule import ScheduleSlot, decode, encode
from .tuya_client import TuyaClient, TuyaClientError

_LOGGER = logging.getLogger(__name__)

# An unacknowledged warning that hasn't cleared within this window is
# considered stale — either the jam fixed itself or the feeder missed a
# self-clear DP write. Mirrors the PetLibro Lite app's home-screen fade.
ACTIVE_WARN_WINDOW_SEC = 60 * 60


@dataclass
class PetLibroState:
    """Parsed snapshot of the device state that entities consume.

    Everything here is normalized to Python types — entities should never have
    to peek at raw DPs or decode hex strings.
    """

    master_on: bool | None
    device_state: str | None            # "standby" | "feeding" | None
    food_level: str | None              # "full" | "low" | "empty" | None
    warning: str | None                 # edge-tracked; "ok" unless we saw a rising edge
    warning_code: int | None            # raw DP 236 int, for unknown codes
    warning_raised_at: int | None       # unix secs when 236 last transitioned 0→N
    last_manual: dict[str, Any] | None  # {"portions": N, "time": unix}
    last_scheduled: dict[str, Any] | None
    schedules: list[ScheduleSlot]       # decoded DP 231
    schedules_raw: str | None           # raw hex, for encoders that want to edit in place
    portions_today: int | None          # first segment of DP 109 "N|N|N"
    daily_counters_raw: str | None      # raw DP 109 value for debugging
    raw_dps: dict[str, Any]             # full DPS dict for debugging / future use


class PetLibroCoordinator(DataUpdateCoordinator[PetLibroState]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: TuyaClient,
        name: str,
        *,
        device_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({name})",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._device_id = device_id
        # Edge-tracking state. None = "we haven't observed a rising DP 236
        # edge since this integration started" — the initial read of a
        # sticky non-zero code counts as neither rising nor falling.
        self._warning_raised_at: int | None = None
        # Last seen raw DP 236 value. Used to detect 0→N rising edges.
        self._prev_warning_code: int | None = None
        # Last event timestamps we've already fired bus events for, so we
        # don't re-announce the same feed every poll. Set lazily on first
        # poll so the initial snapshot doesn't spam the bus with historical
        # entries.
        self._prev_manual_ts: int | None = None
        self._prev_scheduled_ts: int | None = None
        self._first_poll_done = False
        # Sticky DP cache. tinytuya's status() occasionally returns a
        # partial DPs dict — some feeder firmwares drop DP 231 (schedules)
        # or other steady-state DPs from the response when they haven't
        # changed recently. Without a cache, entities flap to empty/None
        # on those polls (users see "no schedules"). We merge the fresh
        # dps over this cache so missing keys fall through to last-known
        # values, then refresh the cache with the merged result.
        self._dp_cache: dict[str, Any] = {}

    async def _async_update_data(self) -> PetLibroState:
        try:
            dps = await self.client.status()
        except TuyaClientError as err:
            raise UpdateFailed(str(err)) from err
        # Normalize keys to strings (tinytuya sometimes uses ints).
        dps = {str(k): v for k, v in dps.items()}
        # Fill gaps from our last-known cache so partial responses don't
        # blank out steady-state DPs like 231 (schedules). New values win
        # over cached ones.
        merged: dict[str, Any] = dict(self._dp_cache)
        merged.update(dps)
        self._dp_cache = merged
        dps = merged
        schedules_raw = dps.get(str(DP_SCHEDULES))
        warn_raw = dps.get(str(DP_WARNING))
        warn_code = int(warn_raw) if isinstance(warn_raw, (int, str)) and str(warn_raw).lstrip("-").isdigit() else None

        last_manual = parse_feed_event(dps.get(str(DP_LAST_MANUAL_FEED)))
        last_scheduled = parse_feed_event(dps.get(str(DP_LAST_SCHEDULED_FEED)))

        now = int(time.time())

        # --- Warning edge tracking ---
        # Rising edge: we saw 0 (or None) last time, and current is non-zero.
        # The very first poll just records the current value — a latched
        # non-zero DP 236 on startup is treated as stale until we observe a
        # real transition.
        if (
            self._prev_warning_code is not None
            and (warn_code or 0) > 0
            and (self._prev_warning_code or 0) == 0
        ):
            self._warning_raised_at = now
            self._fire_warning_event(warn_code or 0, now)
        # Falling edge: device cleared to 0 → clear our tracked warning.
        if (warn_code or 0) == 0:
            self._warning_raised_at = None
        self._prev_warning_code = warn_code

        # --- Derive the user-visible warning value ---
        # "ok" unless we saw a rising edge AND no intervening successful feed
        # AND the edge is still young. Otherwise fall through to the code.
        warn_label: str | None = None
        if self._warning_raised_at is not None:
            last_feed_t = _latest_feed_time(last_manual, last_scheduled)
            age = now - self._warning_raised_at
            feed_cleared = (
                last_feed_t is not None
                and last_feed_t > self._warning_raised_at
            )
            faded = age >= ACTIVE_WARN_WINDOW_SEC
            if not feed_cleared and not faded:
                warn_label = WARNING_LABELS.get(
                    warn_code or 0, f"warning_{warn_code}",
                )
        if warn_label is None:
            warn_label = "ok"

        # --- Feed transition events ---
        manual_ts = last_manual["time"] if last_manual else None
        scheduled_ts = last_scheduled["time"] if last_scheduled else None
        if self._first_poll_done:
            if (
                manual_ts is not None
                and self._prev_manual_ts is not None
                and manual_ts > self._prev_manual_ts
            ):
                self._fire_feed_event("manual", last_manual)
            if (
                scheduled_ts is not None
                and self._prev_scheduled_ts is not None
                and scheduled_ts > self._prev_scheduled_ts
            ):
                self._fire_feed_event("scheduled", last_scheduled)
        self._prev_manual_ts = manual_ts
        self._prev_scheduled_ts = scheduled_ts
        self._first_poll_done = True

        counters_raw = dps.get(str(DP_DAILY_COUNTERS))
        portions_today = parse_daily_counter(counters_raw)

        return PetLibroState(
            master_on=_as_bool(dps.get(str(DP_MASTER_SWITCH))),
            device_state=dps.get(str(DP_DEVICE_STATE)) or None,
            food_level=dps.get(str(DP_FOOD_LEVEL)) or None,
            warning=warn_label,
            warning_code=warn_code,
            warning_raised_at=self._warning_raised_at,
            last_manual=last_manual,
            last_scheduled=last_scheduled,
            schedules=decode(schedules_raw) if isinstance(schedules_raw, str) else [],
            schedules_raw=schedules_raw if isinstance(schedules_raw, str) else None,
            portions_today=portions_today,
            daily_counters_raw=counters_raw if isinstance(counters_raw, str) else None,
            raw_dps=dps,
        )

    def _fire_feed_event(
        self, kind: str, ev: dict[str, Any] | None,
    ) -> None:
        if not ev:
            return
        data = {
            "device_id": self._device_id,
            "kind": kind,
            "time": int(ev["time"]),
            "portions": int(ev.get("portions", 0) or 0),
            "source": "lan",
        }
        _LOGGER.debug("LAN feed event fired: %s", data)
        self.hass.bus.async_fire(EVENT_FEED, data)

    def _fire_warning_event(self, code: int, at: int) -> None:
        label = WARNING_LABELS.get(code, f"warning_{code}")
        data = {
            "device_id": self._device_id,
            "time": at,
            "code": code,
            "label": label,
            "source": "lan",
        }
        _LOGGER.debug("LAN warning event fired: %s", data)
        self.hass.bus.async_fire(EVENT_WARNING, data)

    # -- high-level write helpers ---------------------------------------------

    async def async_feed(self, portions: int) -> None:
        """Trigger a manual feed. Caller has already validated range."""
        await self.client.set_dp(DP_FEED_PORTIONS, int(portions))
        # Device takes ~1–2s to report `feeding`; request a refresh so HA shows
        # the transition promptly. async_request_refresh is debounced (up to
        # ~10s) but that's fine for feed — DP 247 only advances once the feed
        # actually completes, which takes ~1–2s of mechanical time anyway.
        await self.async_request_refresh()

    async def async_set_master(self, on: bool) -> None:
        await self.client.set_dp(DP_MASTER_SWITCH, bool(on))
        await self._async_refresh_after_write()

    async def async_write_schedules(self, slots: list[ScheduleSlot]) -> None:
        """Replace the on-device schedule list. Power-cycle quirks aside, the
        device accepts this wholesale write; there's no incremental add/remove
        protocol to call out to.

        We bypass the refresh debouncer here — schedule edits come from a
        user interaction (card dialog), and seeing the list update take
        10+ seconds feels broken. The 300ms settle is the minimum we need
        for the feeder to finish parsing DP 231 and reflect it in a
        subsequent status read.
        """
        await self.client.set_dp(DP_SCHEDULES, encode(slots))
        await self._async_refresh_after_write()

    async def _async_refresh_after_write(self) -> None:
        """Immediate, un-debounced poll after a DP write.

        tinytuya's set_dp returns as soon as the encrypted packet is sent
        over TCP; the feeder takes ~100–300ms to decode, apply, and be
        ready to report the new value. Sleeping briefly before polling
        avoids a race where we read-back the pre-write state.
        """
        import asyncio as _asyncio
        await _asyncio.sleep(0.3)
        await self.async_refresh()


def _latest_feed_time(
    manual: dict[str, Any] | None,
    scheduled: dict[str, Any] | None,
) -> int | None:
    times = [
        ev.get("time")
        for ev in (manual, scheduled)
        if ev and isinstance(ev.get("time"), (int, float))
    ]
    return int(max(times)) if times else None


def _as_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() == "true"
    return None

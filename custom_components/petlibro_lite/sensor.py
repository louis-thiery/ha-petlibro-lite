"""PetLibro Lite sensor platform.

Feed log is LAN-only: every `petlibro_lite_feed` / `petlibro_lite_warning`
bus event fired by the LAN coordinator is appended to a rolling buffer and
persisted across HA restarts via `RestoreEntity`. On startup the buffer is
seeded from the coordinator's `last_manual` / `last_scheduled` snapshots so
the current day's activity shows up even if the integration was installed
after the most recent feed fired.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    EVENT_FEED,
    EVENT_WARNING,
    LOG_MAX_ENTRIES,
    WARNING_LABELS,
)
from .coordinator import PetLibroCoordinator, PetLibroState
from .entity import PetLibroEntity
from .schedule import compute_next_feed


@dataclass(frozen=True)
class LogEntry:
    """One feed or warning event, as stored in the rolling buffer."""

    kind: str                 # "manual" | "scheduled" | "warning"
    time: int                 # unix seconds
    portions: int | None = None
    code: int | None = None
    label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "time": self.time}
        if self.portions is not None:
            out["portions"] = self.portions
        if self.code is not None:
            out["code"] = self.code
        if self.label is not None:
            out["label"] = self.label
        return out


@dataclass(frozen=True, kw_only=True)
class PetLibroSensorDescription(SensorEntityDescription):
    """Sensor metadata + how to pull the value out of coordinator state.

    We keep the value extractor here (rather than in the entity class) so adding
    a new sensor is a one-line addition to SENSOR_TYPES below.
    """

    value_fn: Callable[[PetLibroState], Any]
    attr_fn: Callable[[PetLibroState], dict[str, Any] | None] = lambda _s: None


def _last_feed_ts(ev: dict[str, Any] | None) -> datetime | None:
    if not ev:
        return None
    return datetime.fromtimestamp(ev["time"], tz=timezone.utc)


def _last_feed_attrs(ev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ev:
        return None
    return {"portions": ev["portions"]}


def _schedule_attrs(state: PetLibroState) -> dict[str, Any]:
    return {
        "slots": [asdict(s) for s in state.schedules],
        "raw": state.schedules_raw,
    }


def _next_feed_ts(state: PetLibroState) -> datetime | None:
    result = compute_next_feed(state.schedules, dt_util.now())
    return result[0] if result else None


def _next_feed_attrs(state: PetLibroState) -> dict[str, Any] | None:
    result = compute_next_feed(state.schedules, dt_util.now())
    if result is None:
        return None
    _when, slot, idx = result
    return {
        "portions": slot.portions,
        "slot_index": idx,
        "days": list(slot.days),
    }


def _warning_attrs(state: PetLibroState) -> dict[str, Any] | None:
    attrs: dict[str, Any] = {"source": "lan"}
    if state.warning_code is not None:
        attrs["lan_code"] = state.warning_code
    if state.warning_raised_at is not None:
        attrs["raised_at"] = datetime.fromtimestamp(
            state.warning_raised_at, tz=timezone.utc,
        ).isoformat()
    return attrs


SENSOR_TYPES: tuple[PetLibroSensorDescription, ...] = (
    PetLibroSensorDescription(
        key="state",
        translation_key="state",
        name="State",
        device_class=SensorDeviceClass.ENUM,
        options=["standby", "feeding"],
        value_fn=lambda s: s.device_state,
    ),
    PetLibroSensorDescription(
        key="food_level",
        translation_key="food_level",
        name="Food level",
        device_class=SensorDeviceClass.ENUM,
        options=["full", "low", "empty"],
        value_fn=lambda s: s.food_level,
    ),
    PetLibroSensorDescription(
        key="warning",
        translation_key="warning",
        name="Warning",
        # Value space includes "warning_<N>" for unknown codes — can't use
        # SensorDeviceClass.ENUM because those aren't pre-declared.
        value_fn=lambda s: s.warning,
        attr_fn=_warning_attrs,
    ),
    PetLibroSensorDescription(
        key="last_manual_feed",
        translation_key="last_manual_feed",
        name="Last manual feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _last_feed_ts(s.last_manual),
        attr_fn=lambda s: _last_feed_attrs(s.last_manual),
    ),
    PetLibroSensorDescription(
        key="last_scheduled_feed",
        translation_key="last_scheduled_feed",
        name="Last scheduled feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _last_feed_ts(s.last_scheduled),
        attr_fn=lambda s: _last_feed_attrs(s.last_scheduled),
    ),
    PetLibroSensorDescription(
        key="schedules",
        translation_key="schedules",
        name="Schedules",
        # Value is the slot count; the useful data is in `slots` attribute.
        # Dashboards can show "4 schedules" at a glance and drill into attrs.
        value_fn=lambda s: len(s.schedules),
        attr_fn=_schedule_attrs,
    ),
    # Next upcoming enabled slot as a timestamp sensor. Mirrors the
    # PetLibro Lite app's prominent "Next Feeding" card. Derived purely
    # from the schedule list, so it stays accurate without any extra DP.
    PetLibroSensorDescription(
        key="next_feed",
        translation_key="next_feed",
        name="Next feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_feed_ts,
        attr_fn=_next_feed_attrs,
    ),
    # `portions_today` is NOT in this list — see PortionsTodaySensor below.
    # DP 109 on PLAF203 firmware doesn't actually track daily counts (stays
    # at "0|0|0" through the day), so we derive the value from observed
    # feed bus events + coordinator-seed instead.
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    device_id = entry.data[CONF_DEVICE_ID]
    entities: list[Any] = [
        PetLibroSensor(runtime.lan, device_id, desc) for desc in SENSOR_TYPES
    ]
    entities.append(FeedLogSensor(runtime.lan, device_id))
    entities.append(PortionsTodaySensor(runtime.lan, device_id))
    async_add_entities(entities)


class PetLibroSensor(PetLibroEntity, SensorEntity):
    entity_description: PetLibroSensorDescription

    def __init__(
        self,
        coordinator: PetLibroCoordinator,
        device_id: str,
        description: PetLibroSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attr_fn(self.coordinator.data)


def _entry_key(e: LogEntry) -> tuple[str, int, int | None]:
    """Stable de-dupe key. (kind, time, portions_or_code)."""
    return (e.kind, int(e.time), e.portions if e.portions is not None else e.code)


class FeedLogSensor(RestoreEntity, SensorEntity):
    """Rolling feed + warning log, LAN-only.

    Fed by `EVENT_FEED` / `EVENT_WARNING` bus events while HA is running,
    persisted across restarts via RestoreEntity, and seeded on startup
    from the coordinator's last-known `last_manual` / `last_scheduled`
    snapshots so the current day's activity stays visible immediately
    after install. No cloud dependency — history before HA saw the
    feeder is simply not available here.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "feed_log"
    _attr_name = "Feed log"

    def __init__(
        self,
        coordinator: PetLibroCoordinator,
        device_id: str,
    ) -> None:
        super().__init__()
        self._coord = coordinator
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_feed_log"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="PetLibro",
            model="PLAF203",
            name=f"PetLibro {device_id[-6:]}",
            serial_number=device_id,
        )
        self._entries: list[LogEntry] = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last = await self.async_get_last_state()
        if last is not None and last.attributes:
            raw = last.attributes.get("entries") or []
            restored: list[LogEntry] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    restored.append(
                        LogEntry(
                            kind=str(item.get("kind", "manual")),
                            time=int(item.get("time", 0)),
                            portions=item.get("portions"),
                            code=item.get("code"),
                            label=item.get("label"),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            self._entries = sorted(
                restored, key=lambda e: e.time, reverse=True,
            )[:LOG_MAX_ENTRIES]

        # Seed from coordinator's last-known feeds. Covers the post-restart /
        # post-install case where the last few feeds landed in DP 247/237
        # before the integration had a chance to subscribe to bus events.
        data = self._coord.data
        if data is not None:
            for kind, ev in (
                ("manual", data.last_manual),
                ("scheduled", data.last_scheduled),
            ):
                if not ev or not isinstance(ev.get("time"), int):
                    continue
                self._add_entry(
                    LogEntry(
                        kind=kind,
                        time=int(ev["time"]),
                        portions=int(ev.get("portions", 0) or 0),
                        code=None,
                        label=None,
                    ),
                    write_state=False,
                )

        # Filter inbound events by device_id so multi-feeder installs don't
        # cross-pollinate each other's logs.
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_FEED, self._on_feed_event)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_WARNING, self._on_warning_event)
        )

        self.async_write_ha_state()

    @callback
    def _on_feed_event(self, event: Event) -> None:
        data = event.data
        if data.get("device_id") != self._device_id:
            return
        try:
            entry = LogEntry(
                kind=str(data.get("kind", "manual")),
                time=int(data.get("time", 0)),
                portions=int(data.get("portions", 0) or 0),
                code=None,
                label=None,
            )
        except (TypeError, ValueError):
            return
        self._add_entry(entry)

    @callback
    def _on_warning_event(self, event: Event) -> None:
        data = event.data
        if data.get("device_id") != self._device_id:
            return
        try:
            code = int(data.get("code", 0))
        except (TypeError, ValueError):
            return
        entry = LogEntry(
            kind="warning",
            time=int(data.get("time", 0)),
            portions=None,
            code=code,
            label=WARNING_LABELS.get(code, f"warning_{code}"),
        )
        self._add_entry(entry)

    def _add_entry(self, entry: LogEntry, *, write_state: bool = True) -> None:
        k = _entry_key(entry)
        for existing in self._entries:
            if _entry_key(existing) == k:
                return
        self._entries.append(entry)
        self._entries.sort(key=lambda e: e.time, reverse=True)
        del self._entries[LOG_MAX_ENTRIES:]
        if write_state:
            self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return len(self._entries)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"entries": [e.as_dict() for e in self._entries]}


class PortionsTodaySensor(RestoreEntity, SensorEntity):
    """Running total of portions dispensed today.

    Data sources, in priority order:

      1. `EVENT_FEED` bus events (real-time, covers both manual and
         scheduled feeds), deduplicated by timestamp.
      2. On startup, the coordinator's `last_manual` / `last_scheduled`
         snapshots are seeded as initial counts if their timestamps fall
         in today — covers feeds that happened before HA started.
      3. RestoreEntity brings the count forward across HA restarts when
         we're still in the same local date.

    DP 109 (first segment of "N|N|N") was the original source but is
    consistently `0` on PLAF203 firmware in the wild — it doesn't
    actually track daily portion counts.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "portions_today"
    _attr_name = "Portions today"
    _attr_icon = "mdi:counter"

    def __init__(
        self, coordinator: PetLibroCoordinator, device_id: str,
    ) -> None:
        super().__init__()
        self._coord = coordinator
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_portions_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="PetLibro",
            model="PLAF203",
            name=f"PetLibro {device_id[-6:]}",
            serial_number=device_id,
        )
        self._date: str | None = None    # ISO date of the day the count covers
        self._count: int = 0
        self._seen_ts: set[int] = set()  # dedupe by feed timestamp

    def _today(self) -> str:
        return dt_util.now().date().isoformat()

    def _start_of_today(self) -> int:
        now = dt_util.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(start.timestamp())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last = await self.async_get_last_state()
        if last is not None and last.attributes:
            attr_date = last.attributes.get("date")
            if attr_date == self._today():
                try:
                    self._count = (
                        int(last.state)
                        if last.state not in (None, "unknown", "unavailable")
                        else 0
                    )
                except (ValueError, TypeError):
                    self._count = 0
                self._date = attr_date
                seen = last.attributes.get("seen_ts") or []
                self._seen_ts = {int(t) for t in seen if isinstance(t, int)}

        # Seed from coordinator's last-known feeds. Covers two cases:
        # (a) post-restart where today's feeds pre-date the integration
        # starting, and (b) cloud backfill bringing historical events in
        # via the coordinator's state before any EVENT_FEED fires.
        data = self._coord.data
        if data is not None:
            start = self._start_of_today()
            for ev in (data.last_manual, data.last_scheduled):
                if not ev:
                    continue
                t = ev.get("time")
                if not isinstance(t, int) or t < start:
                    continue
                if t in self._seen_ts:
                    continue
                self._seen_ts.add(t)
                self._count += int(ev.get("portions", 0) or 0)
                self._date = self._today()

        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_FEED, self._on_feed_event)
        )
        self.async_write_ha_state()

    @callback
    def _on_feed_event(self, event: Event) -> None:
        if event.data.get("device_id") != self._device_id:
            return
        today = self._today()
        if self._date != today:
            # Day rolled — reset before recording the new event.
            self._date = today
            self._count = 0
            self._seen_ts = set()
        try:
            t = int(event.data.get("time", 0))
            portions = int(event.data.get("portions", 0) or 0)
        except (TypeError, ValueError):
            return
        if t in self._seen_ts:
            return
        self._seen_ts.add(t)
        self._count += portions
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        # If runtime rolled past midnight but no new feed has come in yet,
        # surface 0 rather than yesterday's total — matches how
        # `total_increasing` entities behave on reset.
        if self._date is not None and self._date != self._today():
            return 0
        return self._count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "date": self._date,
            "seen_ts": sorted(self._seen_ts),
        }

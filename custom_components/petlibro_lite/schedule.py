"""Encode/decode DP 231 schedule blobs.

Format is a flat concatenation of 5-byte records:
    <day_mask> <hour> <min> <portions> <enabled>

Day mask is a single byte, each bit = one weekday:
    bit 6 = Mon
    bit 5 = Tue
    bit 4 = Wed
    bit 3 = Thu
    bit 2 = Fri
    bit 1 = Sat
    bit 0 = Sun

Observed in the wild:
    7f 08 00 02 00 — every day, 08:00, 2 portions, disabled
    70 01 00 01 01 — Mon/Tue/Wed only, 01:00, 1 portion, enabled
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

DAYS_LSB_TO_MSB: tuple[str, ...] = ("sun", "sat", "fri", "thu", "wed", "tue", "mon")
# Weekday name per Python's `date.weekday()` index (0=Mon … 6=Sun).
DAYS_BY_WEEKDAY: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_BITS: dict[str, int] = {d: 1 << i for i, d in enumerate(DAYS_LSB_TO_MSB)}
ALL_DAYS_MASK = 0x7F


@dataclass
class ScheduleSlot:
    hour: int
    minute: int
    portions: int
    enabled: bool
    # Canonical day list in Mon→Sun order; empty == same meaning as every day
    # would be weird, so we normalize to full set when decoding an all-bits mask.
    days: list[str] = field(default_factory=list)

    @classmethod
    def every_day(
        cls, hour: int, minute: int, portions: int, enabled: bool
    ) -> "ScheduleSlot":
        return cls(
            hour=hour,
            minute=minute,
            portions=portions,
            enabled=enabled,
            days=list(DAYS_LSB_TO_MSB[::-1]),
        )

    @property
    def day_mask(self) -> int:
        mask = 0
        for d in self.days:
            bit = DAY_BITS.get(d.lower())
            if bit is not None:
                mask |= bit
        return mask

    def to_bytes(self) -> bytes:
        if not 0 <= self.hour < 24:
            raise ValueError(f"hour out of range: {self.hour}")
        if not 0 <= self.minute < 60:
            raise ValueError(f"minute out of range: {self.minute}")
        if not 1 <= self.portions <= 50:
            raise ValueError(f"portions out of range: {self.portions}")
        mask = self.day_mask
        if mask == 0:
            raise ValueError("at least one day must be set")
        return bytes(
            [mask, self.hour, self.minute, self.portions, 1 if self.enabled else 0]
        )


def decode(hex_str: str) -> list[ScheduleSlot]:
    """Decode the DP 231 hex string into a list of slots.

    Returns an empty list if the blob is empty or unparseable past the first
    bad byte — partial decoding beats crashing when the device pushes a short
    read during reboot.
    """
    if not hex_str:
        return []
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return []
    slots: list[ScheduleSlot] = []
    for i in range(0, len(raw), 5):
        chunk = raw[i : i + 5]
        if len(chunk) < 5:
            break
        mask, hour, minute, portions, enabled = chunk
        days = [d for d, bit in DAY_BITS.items() if mask & bit]
        # Preserve Mon→Sun display order
        order = {d: i for i, d in enumerate(["mon","tue","wed","thu","fri","sat","sun"])}
        days.sort(key=lambda d: order.get(d, 99))
        slots.append(
            ScheduleSlot(
                hour=hour,
                minute=minute,
                portions=portions,
                enabled=bool(enabled),
                days=days,
            )
        )
    return slots


def encode(slots: list[ScheduleSlot]) -> str:
    """Encode a list of slots into the hex blob the device expects."""
    return b"".join(s.to_bytes() for s in slots).hex()


def compute_next_feed(
    slots: list[ScheduleSlot], now: datetime,
) -> tuple[datetime, ScheduleSlot, int] | None:
    """Find the next enabled feed that will fire after `now`.

    Returns `(when, slot, slot_index)` or `None` if no enabled slot
    repeats within the next 7 days. `now` must be timezone-aware — we
    compose candidate datetimes with its `tzinfo` so DST edges land
    correctly. Caller typically passes `dt_util.now()`.

    We walk days 0..7 and pick the earliest matching slot. "Today"
    only counts if at least one enabled slot's time is still in the
    future — otherwise we fall through to tomorrow.
    """
    if now.tzinfo is None:
        raise ValueError("compute_next_feed requires timezone-aware `now`")

    enabled: list[tuple[int, ScheduleSlot]] = [
        (i, s) for i, s in enumerate(slots) if s.enabled and s.days
    ]
    if not enabled:
        return None

    for offset in range(8):
        candidate_date = (now + timedelta(days=offset)).date()
        weekday_name = DAYS_BY_WEEKDAY[candidate_date.weekday()]
        day_best: tuple[datetime, ScheduleSlot, int] | None = None
        for idx, slot in enabled:
            if weekday_name not in slot.days:
                continue
            when = datetime.combine(
                candidate_date,
                time(slot.hour, slot.minute),
                tzinfo=now.tzinfo,
            )
            if when <= now:
                continue
            if day_best is None or when < day_best[0]:
                day_best = (when, slot, idx)
        if day_best is not None:
            return day_best
    return None

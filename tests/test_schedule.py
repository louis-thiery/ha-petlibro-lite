"""Tests for the DP 231 schedule codec."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schedule import (
    ALL_DAYS_MASK,
    DAY_BITS,
    ScheduleSlot,
    compute_next_feed,
    decode,
    encode,
)


# Real-world production DP 231 blob. Four slots:
#   7f 08 00 02 00 — every day, 08:00, 2 portions, disabled
#   7f 0d 00 02 01 — every day, 13:00, 2 portions, enabled
#   7f 15 00 01 01 — every day, 21:00, 1 portion, enabled
#   7f 12 00 01 01 — every day, 18:00, 1 portion, enabled
PROD_BLOB = "7f080002007f0d0002017f150001017f12000101"


def test_decode_empty_inputs():
    assert decode("") == []
    assert decode("nothex") == []


def test_decode_production_blob():
    slots = decode(PROD_BLOB)
    assert len(slots) == 4
    assert [s.hour for s in slots] == [8, 13, 21, 18]
    assert [s.portions for s in slots] == [2, 2, 1, 1]
    assert [s.enabled for s in slots] == [False, True, True, True]
    # All slots are every-day
    for s in slots:
        assert sorted(s.days) == sorted(DAY_BITS.keys())


def test_decode_weekday_only_slot():
    # 0x70 = 0b0111_0000 = Mon+Tue+Wed only
    blob = "7001000101"
    slots = decode(blob)
    assert len(slots) == 1
    assert slots[0].days == ["mon", "tue", "wed"]
    assert slots[0].hour == 1
    assert slots[0].portions == 1
    assert slots[0].enabled is True


def test_encode_roundtrip_production_blob():
    slots = decode(PROD_BLOB)
    assert encode(slots) == PROD_BLOB


def test_encode_roundtrip_mixed_slots():
    # Synthesized to cover mixed day masks + ends of ranges.
    original = [
        ScheduleSlot.every_day(0, 0, 1, True),
        ScheduleSlot(hour=23, minute=59, portions=50, enabled=False, days=["mon"]),
        ScheduleSlot(hour=6, minute=30, portions=3, enabled=True, days=["sat", "sun"]),
    ]
    blob = encode(original)
    roundtrip = decode(blob)
    assert len(roundtrip) == len(original)
    for orig, got in zip(original, roundtrip):
        assert got.hour == orig.hour
        assert got.minute == orig.minute
        assert got.portions == orig.portions
        assert got.enabled == orig.enabled
        assert sorted(got.days) == sorted(orig.days)


def test_encode_rejects_bad_ranges():
    for bad in (
        ScheduleSlot(hour=24, minute=0, portions=1, enabled=True, days=["mon"]),
        ScheduleSlot(hour=0, minute=60, portions=1, enabled=True, days=["mon"]),
        ScheduleSlot(hour=0, minute=0, portions=0, enabled=True, days=["mon"]),
        ScheduleSlot(hour=0, minute=0, portions=51, enabled=True, days=["mon"]),
        ScheduleSlot(hour=0, minute=0, portions=1, enabled=True, days=[]),
    ):
        with pytest.raises(ValueError):
            bad.to_bytes()


def test_decode_short_trailing_record_is_dropped():
    # Production blob + 3 extra bytes — decoder should silently stop at 20.
    blob = PROD_BLOB + "7f0800"
    slots = decode(blob)
    assert len(slots) == 4


def test_day_mask_all_bits_is_0x7f():
    s = ScheduleSlot.every_day(12, 0, 1, True)
    assert s.day_mask == ALL_DAYS_MASK


# --- compute_next_feed -------------------------------------------------------


def _tuesday_10am() -> datetime:
    # 2026-04-21 is a Tuesday (verified: .weekday() == 1).
    return datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)


def test_compute_next_feed_empty_returns_none():
    assert compute_next_feed([], _tuesday_10am()) is None


def test_compute_next_feed_all_disabled_returns_none():
    slots = [
        ScheduleSlot.every_day(8, 0, 2, enabled=False),
        ScheduleSlot.every_day(20, 0, 1, enabled=False),
    ]
    assert compute_next_feed(slots, _tuesday_10am()) is None


def test_compute_next_feed_same_day_future_slot():
    slots = [
        ScheduleSlot.every_day(8, 0, 2, enabled=True),   # passed
        ScheduleSlot.every_day(14, 0, 1, enabled=True),  # future today
    ]
    result = compute_next_feed(slots, _tuesday_10am())
    assert result is not None
    when, slot, idx = result
    assert when.hour == 14 and when.day == 21
    assert slot.portions == 1
    assert idx == 1


def test_compute_next_feed_rolls_to_next_day():
    slots = [ScheduleSlot.every_day(8, 0, 2, enabled=True)]
    # It's past 8am Tuesday → next feed is Wed 8am
    result = compute_next_feed(slots, _tuesday_10am())
    assert result is not None
    when, _slot, _idx = result
    assert when.day == 22 and when.hour == 8


def test_compute_next_feed_respects_day_mask():
    # Only Wed enabled; current is Tuesday 10am — next feed Wed morning.
    slots = [ScheduleSlot(hour=6, minute=0, portions=2, enabled=True, days=["wed"])]
    result = compute_next_feed(slots, _tuesday_10am())
    assert result is not None
    when, _s, _i = result
    assert when.day == 22  # Wednesday
    assert when.hour == 6


def test_compute_next_feed_requires_aware_datetime():
    with pytest.raises(ValueError):
        compute_next_feed(
            [ScheduleSlot.every_day(8, 0, 2, True)],
            datetime(2026, 4, 21, 10, 0),
        )


def test_compute_next_feed_picks_earliest_of_multiple_same_day():
    # Two enabled slots today: earlier one should win.
    slots = [
        ScheduleSlot.every_day(20, 0, 1, enabled=True),
        ScheduleSlot.every_day(14, 0, 3, enabled=True),
    ]
    result = compute_next_feed(slots, _tuesday_10am())
    assert result is not None
    when, slot, idx = result
    assert when.hour == 14
    assert slot.portions == 3
    assert idx == 1

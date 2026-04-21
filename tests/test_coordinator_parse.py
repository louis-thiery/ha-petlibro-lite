"""Unit tests for coordinator helpers that don't need HA running."""

from __future__ import annotations

from helpers import parse_daily_counter, parse_feed_event


def test_parse_feed_event_valid_json():
    got = parse_feed_event('{"value":2,"time":1776662591}')
    assert got == {"portions": 2, "time": 1776662591}


def test_parse_feed_event_dict_passthrough():
    got = parse_feed_event({"value": 3, "time": 1000})
    assert got == {"portions": 3, "time": 1000}


def test_parse_feed_event_zero_and_none_return_none():
    assert parse_feed_event(0) is None
    assert parse_feed_event("0") is None
    assert parse_feed_event(None) is None
    assert parse_feed_event("") is None


def test_parse_feed_event_garbage_returns_none():
    assert parse_feed_event("not json") is None
    assert parse_feed_event('{"value":1}') is None  # missing time
    assert parse_feed_event('{"time":-1,"value":1}') is None
    assert parse_feed_event('{"time":"nope","value":1}') is None


def test_parse_feed_event_coerces_missing_value_to_zero():
    # Device occasionally publishes `{"time":12345}` with no value during boot.
    # Surface it as portions=0 rather than hiding it — 0 is legitimate info
    # (a write of 232=0 reached the device).
    assert parse_feed_event('{"time":12345}') == {"portions": 0, "time": 12345}


# --- parse_daily_counter (DP 109) --------------------------------------------


def test_parse_daily_counter_production_shape():
    assert parse_daily_counter("0|0|0") == 0
    assert parse_daily_counter("3|5|12") == 3
    assert parse_daily_counter("  7 |1|1") == 7  # tolerates whitespace


def test_parse_daily_counter_rejects_non_pipe_shapes():
    assert parse_daily_counter(None) is None
    assert parse_daily_counter("") is None
    assert parse_daily_counter("3") is None  # no pipe
    assert parse_daily_counter(3) is None    # not a string
    assert parse_daily_counter("|1|2") is None  # empty first segment
    assert parse_daily_counter("abc|def|ghi") is None  # non-numeric

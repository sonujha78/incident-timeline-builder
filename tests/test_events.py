from datetime import datetime, timezone, timedelta

import pytest

from itb.events import make_event, parse_ts, event_from_dict


def test_parse_ts_z_suffix():
    assert parse_ts("2026-01-01T10:00:00Z") == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_parse_ts_offset_converted_to_utc():
    # 15:30 in IST (+05:30) is 10:00 UTC
    assert parse_ts("2026-01-01T15:30:00+05:30") == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_parse_ts_naive_uses_assumed_zone():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert parse_ts("2026-01-01 15:30:00", assume_tz=ist) == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_parse_ts_epoch():
    assert parse_ts(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_make_event_redacts_description_and_attrs():
    ev = make_event("2026-01-01T10:00:00Z", "applog", "error_log", "web",
                    "login failed password=hunter2", attrs={"hdr": "token=abc12345"})
    assert "hunter2" not in ev.description
    assert "abc12345" not in str(ev.attrs)


def test_event_id_is_deterministic():
    a = make_event("2026-01-01T10:00:00Z", "git", "deploy", "web", "deploy v2")
    b = make_event("2026-01-01T10:00:00Z", "git", "deploy", "web", "deploy v2")
    assert a.event_id == b.event_id
    c = make_event("2026-01-01T10:00:01Z", "git", "deploy", "web", "deploy v2")
    assert a.event_id != c.event_id


def test_invalid_type_and_source_rejected():
    with pytest.raises(ValueError):
        make_event("2026-01-01T10:00:00Z", "git", "bogus", "web", "x")
    with pytest.raises(ValueError):
        make_event("2026-01-01T10:00:00Z", "nope", "deploy", "web", "x")


def test_roundtrip_dict():
    ev = make_event("2026-01-01T10:00:00Z", "docker", "restart", "web", "container restarted",
                    attrs={"exit_code": 137})
    back = event_from_dict(ev.to_dict())
    assert back.event_id == ev.event_id
    assert back.ts == ev.ts
    assert back.attrs == ev.attrs

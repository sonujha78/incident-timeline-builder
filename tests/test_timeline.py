import random

from itb.events import make_event
from itb.timeline import merge, format_timeline


def ev(ts, source, type, service="web", desc="x"):
    return make_event(ts, source, type, service, desc)


def sample():
    return [
        ev("2026-01-01T10:00:02Z", "health", "health_fail", desc="fail"),
        ev("2026-01-01T10:00:00Z", "git", "deploy", desc="deploy"),
        ev("2026-01-01T10:00:02Z", "applog", "error_log", desc="boom"),
        ev("2026-01-01T10:00:01Z", "docker", "restart", desc="restart"),
    ]


def test_sorted_by_time_then_source_order():
    out = merge(sample())
    assert [e.description for e in out] == ["deploy", "restart", "boom", "fail"]


def test_order_does_not_depend_on_input_order():
    base = [e.event_id for e in merge(sample())]
    for seed in range(20):
        items = sample()
        random.Random(seed).shuffle(items)
        assert [e.event_id for e in merge(items)] == base


def test_exact_duplicates_are_dropped():
    items = sample() + sample()
    assert len(merge(items)) == 4


def test_format_shows_skew_note():
    from dataclasses import replace
    e = replace(sample()[1], skew_applied_s=-60.0)
    text = format_timeline([e])
    assert "[skew -60.0s]" in text and "deploy" in text

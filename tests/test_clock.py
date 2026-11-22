from itb.clock import correct_clocks
from itb.config import load_config
from itb.events import make_event
from itb.timeline import merge


def ev(ts, source, type, service="web", desc="x"):
    return make_event(ts, source, type, service, desc)


def cfg(**auto):
    c = load_config(None)["clock"]
    c["auto"].update(auto)
    return c


def test_git_clock_ahead_is_corrected_and_order_fixed():
    # real: deploy 10:00:00 -> restart 10:00:05. git clock is 60s ahead.
    events = [
        ev("2026-01-01T10:01:00Z", "git", "deploy", desc="d1"),
        ev("2026-01-01T10:00:05Z", "docker", "restart", desc="r1"),
        ev("2026-01-01T10:11:00Z", "git", "deploy", desc="d2"),
        ev("2026-01-01T10:10:05Z", "docker", "restart", desc="r2"),
    ]
    # raw order is wrong: restart appears before its deploy
    assert [e.description for e in merge(events)][:2] == ["r1", "d1"]
    fixed, est = correct_clocks(events, cfg())
    assert est["git"].applied and est["git"].offset_s == -60.0
    assert [e.description for e in merge(fixed)] == ["d1", "r1", "d2", "r2"]


def test_inconsistent_anchors_are_not_applied():
    events = [
        ev("2026-01-01T10:01:00Z", "git", "deploy"),
        ev("2026-01-01T10:00:05Z", "docker", "restart"),
        ev("2026-01-01T10:11:00Z", "git", "deploy"),
        ev("2026-01-01T10:10:35Z", "docker", "restart"),   # offset -30 vs -60
    ]
    fixed, est = correct_clocks(events, cfg())
    assert not est["git"].applied
    assert "disagree" in est["git"].reason
    assert all(e.skew_applied_s == 0 for e in fixed)


def test_single_anchor_pair_not_enough():
    events = [ev("2026-01-01T10:01:00Z", "git", "deploy"),
              ev("2026-01-01T10:00:05Z", "docker", "restart")]
    _, est = correct_clocks(events, cfg())
    assert not est["git"].applied and est["git"].n_pairs == 1


def test_tiny_offset_is_treated_as_real_delay():
    events = [
        ev("2026-01-01T10:00:00Z", "git", "deploy"),
        ev("2026-01-01T10:00:05.5Z", "docker", "restart"),
        ev("2026-01-01T10:10:00Z", "git", "deploy"),
        ev("2026-01-01T10:10:05.5Z", "docker", "restart"),
    ]
    _, est = correct_clocks(events, cfg())
    assert not est["git"].applied


def test_manual_skew_wins_over_auto():
    c = cfg()
    c["manual_skew_s"] = {"applog": -90}
    events = [ev("2026-01-01T10:00:00Z", "applog", "error_log"),
              ev("2026-01-01T10:00:00Z", "docker", "restart")]
    fixed, est = correct_clocks(events, c)
    assert est["applog"].method == "manual"
    log = [e for e in fixed if e.source == "applog"][0]
    assert log.ts.isoformat() == "2026-01-01T09:58:30+00:00"
    assert log.raw_ts.isoformat() == "2026-01-01T10:00:00+00:00"   # raw kept
    assert log.skew_applied_s == -90


def test_reference_source_is_never_changed():
    events = [ev("2026-01-01T10:00:05Z", "docker", "restart")]
    fixed, est = correct_clocks(events, cfg())
    assert est["docker"].method == "reference"
    assert fixed[0].ts == events[0].ts

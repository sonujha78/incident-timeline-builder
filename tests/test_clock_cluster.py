from pathlib import Path

import pytest

from itb.clock import correct_clocks
from itb.config import load_config
from itb.events import make_event
from itb.pipeline import analyze
from itb.replay import load_events

ROOT = Path(__file__).resolve().parents[1]


def ev(ts, source, type, desc="x", service="web", **attrs):
    return make_event(ts, source, type, service, desc, attrs=attrs)


def clock_cfg(**auto):
    c = load_config(None)["clock"]
    c["auto"].update(auto)
    return c


def test_skew_larger_than_deploy_spacing_is_still_found():
    # real deploys: 10:00:00 and 10:00:30. git clock is 60s ahead, which is MORE
    # than the 30s between the deploys (the old nearest-to-zero rule failed here).
    events = [
        ev("2026-01-01T10:01:00Z", "git", "deploy", "d1"),
        ev("2026-01-01T10:00:00.5Z", "docker", "restart", "s1", action="start"),
        ev("2026-01-01T10:01:30Z", "git", "deploy", "d2"),
        ev("2026-01-01T10:00:30.5Z", "docker", "restart", "s2", action="start"),
    ]
    _, est = correct_clocks(events, clock_cfg())
    assert est["git"].applied and est["git"].n_pairs == 2
    assert est["git"].offset_s == pytest.approx(-64.5)


def test_ref_action_ignores_kill_and_die_events():
    anchors = [{"source": "git", "type": "deploy", "ref_source": "docker",
                "ref_type": "restart", "ref_action": "start", "expected_lag_s": 5}]
    events = []
    for git_ts, base in (("10:01:00", "10:00:00"), ("10:11:00", "10:10:00")):
        events += [
            ev(f"2026-01-01T{git_ts}Z", "git", "deploy", f"d{base}"),
            ev(f"2026-01-01T{base}.1Z", "docker", "restart", "k", action="kill"),
            ev(f"2026-01-01T{base}.5Z", "docker", "restart", "s", action="start"),
        ]
    _, est = correct_clocks(events, clock_cfg(anchors=anchors))
    assert est["git"].offset_s == pytest.approx(-64.5)


@pytest.mark.parametrize("name", ["bad_deploy", "failing_dependency",
                                  "resource_exhaustion", "no_clear_cause"])
def test_recorded_incidents_get_their_git_clock_corrected(name):
    cfg = load_config(str(ROOT / "config" / "demo.yaml"))
    a = analyze(load_events(ROOT / "data" / "incidents" / name, cfg), cfg)
    est = a.estimates["git"]
    assert est.applied, est.reason
    assert -64 <= est.offset_s <= -58          # injected skew is +60s

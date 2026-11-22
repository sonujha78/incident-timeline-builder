import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from itb.config import load_config
from itb.events import make_event
from itb.pipeline import analyze
from itb.postmortem import generate_postmortem

BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def at(sec):
    return BASE + timedelta(seconds=sec)


def bad_deploy_events(recover=True, extra=()):
    ev = [
        make_event(at(50), "git", "deploy", "web", "def5678 switch driver",
                   attrs={"sha": "def5678", "author": "dev", "files": ["app/db.py"]}),
        make_event(at(55), "docker", "restart", "web", "container itb-web start",
                   attrs={"action": "start"}),
    ]
    for s in (68, 71, 74, 77, 80):
        ev.append(make_event(at(s), "applog", "error_log", "web",
                             "unsupported protocol in new driver"))
    last = 360 if recover else 150
    for s in range(-100, last + 1, 5):
        bad = (65 <= s < 195) if recover else (s >= 65)
        ev.append(make_event(at(s), "health", "health_fail" if bad else "health_ok",
                             "web", "probe", attrs={"error_rate": 0.45 if bad else 0.0}))
    ev.extend(extra)
    return ev


def run(events, cfg=None):
    cfg = cfg or load_config(None)
    a = analyze(events, cfg)
    return a, cfg, generate_postmortem(a, cfg)


def test_report_has_all_required_sections():
    _, _, md = run(bad_deploy_events())
    for heading in ("## Summary", "## Impact", "## Timeline", "## Most likely trigger",
                    "## Confidence", "## What to check next"):
        assert heading in md


def test_report_names_the_trigger_and_real_numbers():
    _, _, md = run(bad_deploy_events())
    assert "def5678" in md and "app/db.py" in md
    assert "HIGH" in md and "89.0/100" in md
    assert "2m 10s (130s)" in md                 # TTR
    assert "| Time to detect (TTD) | 10s |" in md
    assert "unsupported protocol in new driver" in md


def test_report_is_identical_on_repeat_runs_and_shuffled_input():
    events = bad_deploy_events()
    _, _, first = run(events)
    _, _, second = run(events)
    shuffled = list(events)
    random.Random(1).shuffle(shuffled)
    _, _, third = run(shuffled)
    assert first == second == third


def test_secrets_never_reach_the_report():
    extra = [make_event(at(72), "applog", "error_log", "web",
                        "login failed password=hunter2 token=abc12345xyz")]
    _, _, md = run(bad_deploy_events(extra=extra))
    assert "hunter2" not in md and "abc12345xyz" not in md
    assert "[REDACTED]" in md


def test_final_redaction_layer_catches_leaks():
    cfg = load_config(None)
    a = analyze(bad_deploy_events(), cfg)
    leaked = tuple(replace(e, description="db password=hunter2 failed")
                   if e.type == "error_log" else e for e in a.timeline)
    md = generate_postmortem(replace(a, timeline=leaked), cfg)
    assert "hunter2" not in md


def test_repeated_log_lines_are_collapsed():
    _, _, md = run(bad_deploy_events())
    assert "x5 until 10:01:20Z" in md


def test_pipe_in_description_is_escaped_in_table():
    extra = [make_event(at(72), "applog", "error_log", "web", "a | b")]
    _, _, md = run(bad_deploy_events(extra=extra))
    assert "a \\| b" in md


def test_no_incident_report():
    events = [make_event(at(s), "health", "health_ok", "web", "probe",
                         attrs={"error_rate": 0.0}) for s in range(0, 100, 5)]
    a, _, md = run(events)
    assert a.incident is None
    assert "No incident was detected" in md


def test_no_clear_cause_is_low_confidence_and_says_so():
    events = [e for e in bad_deploy_events()
              if e.type not in ("deploy", "config", "restart")]
    _, _, md = run(events)
    assert "No clear trigger" in md
    assert "**LOW**" in md
    assert "cannot name a cause" in md


def test_next_steps_for_a_deploy_point_to_the_diff():
    _, _, md = run(bad_deploy_events())
    assert "git show def5678" in md


def test_ongoing_incident_is_reported_as_ongoing():
    a, _, md = run(bad_deploy_events(recover=False))
    assert a.incident.ongoing
    assert "still ongoing" in md
    assert "n/a (ongoing)" in md


def test_timeline_row_cap_keeps_markers():
    extra = [make_event(at(-90 + i * 2), "applog", "info", "web", f"note {i}")
             for i in range(30)]
    cfg = load_config(None)
    cfg["report"]["max_timeline_rows"] = 10
    _, _, md = run(bad_deploy_events(extra=extra), cfg)
    assert "omitted" in md
    assert "**Incident start" in md and "**Recovered" in md

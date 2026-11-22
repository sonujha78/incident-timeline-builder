import random
from datetime import datetime, timedelta, timezone

import pytest

from itb.clock import SkewEstimate
from itb.config import load_config
from itb.detect import Incident
from itb.events import make_event
from itb.rank import (assess_confidence, caveats_from_clocks, format_suspect,
                      rank_suspects)

BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def at(sec):
    return BASE + timedelta(seconds=sec)


def cfg(**over):
    c = load_config(None)["ranking"]
    c.update(over)
    return c


def incident(start=400, detected=410, end=500, service="web", interval=5.0):
    return Incident(service=service, start=at(start), detected_at=at(detected),
                    end=at(end) if end is not None else None, probe_count=10,
                    bad_probe_count=10, peak_error_rate=0.5,
                    probe_interval_s=interval, reason="test")


def change(sec, type="deploy", service="web", desc="change", **attrs):
    source = "docker" if type == "restart" else "git"
    return make_event(at(sec), source, type, service, desc, attrs=attrs)


def probe(sec, ok=True, service="web"):
    return make_event(at(sec), "health", "health_ok" if ok else "health_fail",
                      service, "probe")


def errlog(sec, msg="boom", service="web"):
    return make_event(at(sec), "applog", "error_log", service, msg)


def rank(events, inc=None, **over):
    return rank_suspects(events, inc or incident(), cfg(**over))


def names(r):
    return [s.event.description for s in r.suspects]


def clear_case():
    return [change(385, desc="culprit"), errlog(392), errlog(395), errlog(398)]


def test_closer_change_ranks_higher():
    r = rank([change(380, desc="near"), change(100, desc="far")])
    assert names(r) == ["near", "far"]
    assert r.suspects[0].score > r.suspects[1].score


def test_components_add_up_to_score():
    events = [change(100, desc="old")] + [probe(t) for t in range(105, 400, 5)]
    s = rank(events).suspects[0]
    assert s.score == round(sum(c.points for c in s.components), 1)
    assert all(c.detail for c in s.components)       # every number has a reason


def test_exact_score_for_known_case():
    s = rank(clear_case()).suspects[0]
    got = {c.name: c.points for c in s.components}
    assert got == {"proximity": 39.0, "change_type": 20.0, "relation": 15.0,
                   "corroboration": 15.0, "evidence": 0.0, "stability": 0.0}
    assert s.score == pytest.approx(89.0)
    assert s.rank == 1 and s.lead_time_s == 15


def test_stable_service_gets_penalty():
    events = [change(100, desc="old")] + [probe(t) for t in range(105, 400, 5)]
    comps = {c.name: c for c in rank(events).suspects[0].components}
    assert comps["stability"].points == -25.0
    assert "healthy" in comps["stability"].detail


def test_bad_probe_between_cancels_penalty():
    events = [change(100, desc="old")] + \
        [probe(t, ok=(t != 200)) for t in range(105, 400, 5)]
    comps = {c.name: c for c in rank(events).suspects[0].components}
    assert comps["stability"].points == 0.0


def test_dependency_is_linked_through_error_logs():
    events = [
        change(380, "restart", "db", "container itb-db die", action="die", exit_code="137"),
        change(385, "deploy", "worker", "unrelated worker deploy"),
        errlog(395, "connection refused to db:5432"),
        errlog(398, "connection refused to db:5432"),
        errlog(401, "connection refused to db:5432"),
    ]
    r = rank(events)
    top = r.suspects[0]
    assert top.event.service == "db"
    by = {c.name: c for c in top.components}
    assert by["relation"].points == 15 and "db" in by["relation"].detail
    assert by["evidence"].points == 10
    worker = {c.name: c for c in r.suspects[1].components}
    assert worker["relation"].points == 0


def test_own_oom_is_a_symptom_not_a_suspect():
    events = [change(300, desc="deploy"),
              change(395, "restart", "web", "container itb-web OOM killed", action="oom")]
    r = rank(events)
    assert names(r) == ["deploy"]
    assert len(r.suppressed) == 1 and "symptom" in r.suppressed[0][1]


def test_container_start_after_deploy_is_rollout_not_suspect():
    events = [change(380, desc="the deploy"),
              change(385, "restart", "web", "container itb-web start", action="start")]
    r = rank(events)
    assert names(r) == ["the deploy"]
    assert "rollout" in r.suppressed[0][1]


def test_change_just_after_start_is_kept_but_later_is_not():
    events = [change(403, desc="inside tolerance"), change(460, desc="rollback")]
    assert names(rank(events)) == ["inside tolerance"]


def test_change_outside_lookback_is_ignored():
    events = [change(200, desc="ancient"), change(900, desc="recent")]
    r = rank(events, inc=incident(start=1000, detected=1010, end=1100))
    assert names(r) == ["recent"]


def test_no_changes_means_low_confidence():
    r = rank([errlog(395), probe(405, ok=False)])
    conf = assess_confidence(r.suspects, cfg())
    assert r.suspects == ()
    assert conf.level == "low"
    assert "no change" in conf.reasons[0]


def test_clear_winner_is_high_confidence():
    conf = assess_confidence(rank(clear_case()).suspects, cfg())
    assert conf.level == "high" and conf.top_score == 89.0


def test_close_scores_are_low_confidence():
    events = [change(385, desc="a"), change(383, desc="b"),
              errlog(392), errlog(395), errlog(398)]
    r = rank(events)
    conf = assess_confidence(r.suspects, cfg())
    assert conf.level == "low"
    assert "close" in " ".join(conf.reasons)


def test_caveat_lowers_high_to_medium():
    r = rank(clear_case())
    conf = assess_confidence(r.suspects, cfg(), caveats=("clock of 'git' is unsure",))
    assert conf.level == "medium"
    assert "downgraded" in " ".join(conf.reasons)


def test_caveats_from_unapplied_clock():
    bad = SkewEstimate("git", -30.0, 2, 30.0, False, "auto",
                       "anchor offsets disagree (spread 30.0s > 10s); not corrected")
    ref = SkewEstimate("docker", 0.0, 0, 0.0, False, "reference", "reference clock")
    assert len(caveats_from_clocks({"git": bad, "docker": ref})) == 1
    assert "git" in caveats_from_clocks({"git": bad})[0]
    assert caveats_from_clocks({"docker": ref}) == []


def test_ranking_is_order_independent():
    events = ([change(380, desc="near"), change(100, desc="far")]
              + [errlog(395), errlog(398)] + [probe(t) for t in range(105, 400, 5)])
    base = [(s.event.event_id, s.score) for s in rank(events).suspects]
    for seed in range(20):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        assert [(s.event.event_id, s.score) for s in rank(shuffled).suspects] == base


def test_explanation_text_shows_every_component():
    text = format_suspect(rank(clear_case()).suspects[0])
    for name in ("proximity", "change_type", "relation", "corroboration",
                 "evidence", "stability"):
        assert name in text
    assert "89.0" in text and "culprit" in text

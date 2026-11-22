"""Ranking demo: a bad deploy with two decoy changes; the git clock runs 60s ahead."""

from datetime import datetime, timedelta, timezone

from itb.config import load_config
from itb.detect import detect_incidents, primary_incident
from itb.events import make_event
from itb.metrics import compute_metrics, format_metrics
from itb.rank import (assess_confidence, caveats_from_clocks, format_ranking,
                      rank_suspects)
from itb.timeline import build_timeline, merge

T0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
SKEW = 60                      # git clock is 60s ahead of real time
E = make_event


def t(sec):
    return T0 + timedelta(seconds=sec)


def build_events():
    ev = []
    # git: real times (seconds from 10:00:00) shifted by the skewed clock
    for sec, typ, msg in [(-480, "config", "a1b2c3d tune log level"),
                          (-120, "deploy", "abc1234 refactor cache"),
                          (50, "deploy", "def5678 switch to new db driver"),
                          (190, "deploy", "9f8e7d6 rollback def5678")]:
        ev.append(E(t(sec + SKEW), "git", typ, "web", msg))
    # docker (reference clock): container start 5s after every deploy
    for sec in (-115, 55, 195):
        ev.append(E(t(sec), "docker", "restart", "web", "container itb-web start",
                    attrs={"action": "start"}))
    # app errors caused by the bad deploy
    for sec in (68, 71, 74, 77, 80):
        ev.append(E(t(sec), "applog", "error_log", "web",
                    "unsupported protocol in new driver"))
    # health probes every 5s, failing from +65s until the rollback takes effect
    for sec in range(-300, 361, 5):
        bad = 65 <= sec < 195
        ev.append(E(t(sec), "health", "health_fail" if bad else "health_ok", "web",
                    "probe", attrs={"error_rate": 0.45 if bad else 0.0}))
    return ev


def analyse(title, events, correct=True):
    cfg = load_config()
    if correct:
        timeline, est = build_timeline(events, cfg["clock"])
    else:
        timeline, est = merge(events), {}
    inc = primary_incident(detect_incidents(timeline, cfg["detection"]))
    print(f"\n{'=' * 10} {title} {'=' * 10}")
    if inc is None:
        print("no incident detected")
        return
    ranking = rank_suspects(timeline, inc, cfg["ranking"], cfg["detection"])
    conf = assess_confidence(ranking.suspects, cfg["ranking"], caveats_from_clocks(est))
    print(format_ranking(ranking, conf, cfg["ranking"]["top_n"]))
    top = ranking.suspects[0] if ranking.suspects else None
    print(format_metrics(compute_metrics(inc, top)))


if __name__ == "__main__":
    events = build_events()
    analyse("1) clocks corrected (truth: deploy def5678)", events, correct=True)
    analyse("2) WITHOUT clock correction", events, correct=False)
    no_changes = [e for e in events if e.type not in ("deploy", "config", "restart")]
    analyse("3) incident with no recorded change", no_changes, correct=True)

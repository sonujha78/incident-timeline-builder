from test_rank import change, errlog, probe, rank


def comps(r, i=0):
    return {c.name: c for c in r.suspects[i].components}


def test_probe_blips_during_a_rollout_do_not_cancel_the_penalty():
    events = [change(100, desc="old decoy"), probe(101, ok=False), probe(102, ok=False)] \
        + [probe(t) for t in range(105, 400, 5)]
    assert comps(rank(events))["stability"].points == -25.0


def test_failure_well_after_a_rollout_still_cancels_the_penalty():
    events = [change(100, desc="old decoy"), probe(112, ok=False)] \
        + [probe(t) for t in range(115, 400, 5)]
    assert comps(rank(events))["stability"].points == 0.0


def test_error_logs_just_after_detection_still_corroborate():
    events = [change(398, "restart", "db", "container itb-db kill", action="kill",
                     container="itb-db")] \
        + [errlog(412 + i, "connection refused to db:8081") for i in range(3)]
    c = comps(rank(events))
    assert c["relation"].points == 15 and c["corroboration"].points == 15
    off = comps(rank(events, symptom_window_s=0))
    assert off["relation"].points == 0

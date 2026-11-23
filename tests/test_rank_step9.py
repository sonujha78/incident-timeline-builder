from itb.rank import assess_confidence
from test_rank import cfg, change, clear_case, errlog, probe, rank


def lone_decoy():
    return ([change(220, desc="old harmless deploy")]
            + [probe(t) for t in range(225, 400, 5)]
            + [errlog(392), errlog(395), errlog(398)])


def test_lone_old_deploy_cannot_reach_medium_or_high():
    r = rank(lone_decoy())
    top = r.suspects[0]
    comps = {c.name: c for c in top.components}
    assert comps["stability"].points == -25.0
    assert top.score >= 50            # convincing-looking score without the cap
    conf = assess_confidence(r.suspects, cfg())
    assert conf.level == "low"
    assert "capped at low" in " ".join(conf.reasons)


def test_recent_change_without_penalty_is_not_capped():
    conf = assess_confidence(rank(clear_case()).suspects, cfg())
    assert conf.level == "high"
    assert "capped" not in " ".join(conf.reasons)

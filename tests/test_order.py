from itb.rank import assess_confidence, caveats_from_order
from test_rank import cfg, change, clear_case, rank


def test_normal_order_has_no_caveat():
    events = [change(100, desc="d"),
              change(105, "restart", "web", "container start", action="start")]
    assert caveats_from_order(events) == []


def test_start_before_its_deploy_is_flagged():
    events = [change(110, desc="d"),
              change(55, "restart", "web", "container start", action="start")]
    out = caveats_from_order(events)
    assert len(out) == 1 and "disagree" in out[0]


def test_other_service_is_not_flagged():
    events = [change(110, desc="web deploy"),
              change(55, "restart", "db", "container start", action="start")]
    assert caveats_from_order(events) == []


def test_severe_caveat_forces_low_even_with_high_score():
    suspects = rank(clear_case()).suspects
    assert assess_confidence(suspects, cfg()).level == "high"
    conf = assess_confidence(suspects, cfg(), severe=("clocks disagree",))
    assert conf.level == "low"
    assert "forced to low" in " ".join(conf.reasons)

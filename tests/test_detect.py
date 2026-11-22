import random
from datetime import datetime, timezone, timedelta

from itb.config import load_config
from itb.detect import detect_incidents, primary_incident, is_bad_probe
from itb.events import make_event

BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def cfg(**over):
    c = load_config(None)["detection"]
    c.update(over)
    return c


def probe(sec, ok=True, service="web", **attrs):
    return make_event(BASE + timedelta(seconds=sec), "health",
                      "health_ok" if ok else "health_fail", service, "probe",
                      attrs=attrs)


def seq(pattern, start=0, step=5, service="web"):
    """'g' = good probe, 'b' = bad probe, one every `step` seconds."""
    return [probe(start + i * step, ok=(c == "g"), service=service)
            for i, c in enumerate(pattern)]


def at(sec):
    return BASE + timedelta(seconds=sec)


def test_basic_incident_window():
    incs = detect_incidents(seq("ggg" + "bbbbbb" + "gggg"), cfg())
    assert len(incs) == 1
    i = incs[0]
    assert i.start == at(15)          # first bad probe
    assert i.detected_at == at(25)    # 3rd bad probe
    assert i.end == at(45)            # first good probe of the recovery
    assert i.duration_s == 30
    assert i.bad_probe_count == 6 and i.probe_count == 6
    assert not i.ongoing


def test_short_blip_is_ignored():
    assert detect_incidents(seq("gggbbggg"), cfg()) == []


def test_ongoing_incident_has_no_end():
    i = detect_incidents(seq("gggbbbbbb"), cfg())[0]
    assert i.ongoing and i.end is None and i.duration_s is None


def test_one_good_probe_does_not_end_incident():
    incs = detect_incidents(seq("gggbbbgbbbgggg"), cfg())
    assert len(incs) == 1
    assert incs[0].start == at(15) and incs[0].end == at(50)


def test_error_rate_threshold_counts_even_if_probe_ok():
    high = [probe(i * 5, ok=True, error_rate=0.2) for i in range(3)]
    low = [probe(i * 5, ok=True, error_rate=0.01) for i in range(3)]
    assert len(detect_incidents(high, cfg())) == 1
    assert detect_incidents(low, cfg()) == []
    assert is_bad_probe(high[0], cfg())
    assert not is_bad_probe(low[0], cfg())


def test_latency_threshold_is_configurable_and_off_by_default():
    slow = [probe(i * 5, ok=True, latency_ms=900) for i in range(3)]
    assert detect_incidents(slow, cfg()) == []
    assert len(detect_incidents(slow, cfg(latency_ms_threshold=500))) == 1


def test_flapping_is_merged_into_one_incident():
    incs = detect_incidents(seq("gggbbbgggbbbggg"), cfg())
    assert len(incs) == 1
    assert incs[0].start == at(15) and incs[0].end == at(60)


def test_far_apart_incidents_stay_separate():
    incs = detect_incidents(seq("bbb" + "g" * 20 + "bbb" + "gggg"), cfg())
    assert len(incs) == 2
    assert incs[0].start == at(0) and incs[1].start == at(115)


def test_services_are_independent():
    events = seq("gggbbbbbbgggg", service="web") + seq("g" * 13, service="db")
    incs = detect_incidents(events, cfg())
    assert [i.service for i in incs] == ["web"]


def test_min_duration_drops_tiny_incident():
    events = seq("ggbggg")
    assert detect_incidents(events, cfg(start_consecutive=1, min_duration_s=20)) == []
    assert len(detect_incidents(events, cfg(start_consecutive=1, min_duration_s=0))) == 1


def test_start_is_within_one_probe_interval_of_truth():
    true_start = at(12)                       # real failure began between probes
    i = detect_incidents(seq("gggbbbbbbgggg"), cfg())[0]
    assert i.probe_interval_s == 5.0
    assert abs((i.start - true_start).total_seconds()) <= i.probe_interval_s


def test_no_health_signal_means_no_incident():
    logs = [make_event(at(1), "applog", "error_log", "web", "boom")]
    assert detect_incidents(logs, cfg()) == []


def test_primary_incident_is_the_biggest():
    events = seq("bbb" + "g" * 20 + "bbbbbbbb" + "gggg")
    incs = detect_incidents(events, cfg())
    assert len(incs) == 2
    assert primary_incident(incs).bad_probe_count == 8
    assert primary_incident([]) is None


def test_result_does_not_depend_on_input_order():
    events = seq("gggbbbbbbgggg")
    base = [i.to_dict() for i in detect_incidents(events, cfg())]
    for seed in range(10):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        assert [i.to_dict() for i in detect_incidents(shuffled, cfg())] == base

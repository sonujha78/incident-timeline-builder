from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from itb.detect import Incident
from itb.metrics import compute_metrics, format_metrics

BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def inc(end):
    return Incident(service="web", start=BASE + timedelta(seconds=100),
                    detected_at=BASE + timedelta(seconds=110),
                    end=None if end is None else BASE + timedelta(seconds=end),
                    probe_count=10, bad_probe_count=10, peak_error_rate=0.5,
                    probe_interval_s=5.0, reason="test")


def test_ttd_ttr_for_closed_incident():
    m = compute_metrics(inc(190), SimpleNamespace(lead_time_s=15.0))
    assert m["ttd_s"] == 10
    assert m["ttr_s"] == 90
    assert m["recovery_after_detection_s"] == 80
    assert m["change_to_impact_s"] == 15.0
    assert "TTD" in format_metrics(m)


def test_ongoing_incident_has_no_ttr():
    m = compute_metrics(inc(None))
    assert m["ttr_s"] is None and m["recovery_after_detection_s"] is None
    assert m["change_to_impact_s"] is None
    assert "ongoing" in format_metrics(m)

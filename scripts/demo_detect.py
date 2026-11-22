"""Detection demo: one short blip (ignored) and one real incident."""

from datetime import datetime, timedelta, timezone

from itb.config import load_config
from itb.detect import detect_incidents, format_incident
from itb.events import make_event

BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
TRUE_START, TRUE_END = 62, 147        # ground truth, seconds after BASE

events = []
for t in range(0, 301, 5):            # one probe every 5s
    in_incident = 65 <= t < 150
    blip = t == 20
    bad = in_incident or blip
    events.append(make_event(
        BASE + timedelta(seconds=t), "health",
        "health_fail" if bad else "health_ok", "web", "probe",
        attrs={"error_rate": 0.45 if in_incident else (0.3 if blip else 0.0)}))

cfg = load_config()["detection"]
incidents = detect_incidents(events, cfg)
print(f"probes: {len(events)}, blip at 10:00:20 should be ignored")
print(f"incidents found: {len(incidents)}\n")
for inc in incidents:
    print(format_incident(inc))
    ds = (inc.start - (BASE + timedelta(seconds=TRUE_START))).total_seconds()
    de = (inc.end - (BASE + timedelta(seconds=TRUE_END))).total_seconds()
    print(f"\nvs ground truth: start error {ds:+.0f}s, end error {de:+.0f}s "
          f"(allowed: +/- {inc.probe_interval_s}s)")

"""Health probe collector. Reads health.jsonl (one probe per line):

{"ts": "...", "service": "web", "ok": false, "latency_ms": 1500, "error_rate": 0.4}
"""

import json

from ..events import make_event, parse_ts


def collect(path, tz=None):
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ts = parse_ts(rec["ts"], assume_tz=tz) if tz else parse_ts(rec["ts"])
            ok = bool(rec.get("ok", True))
            attrs = {k: rec[k] for k in ("latency_ms", "error_rate", "status")
                     if k in rec}
            desc = "health check ok" if ok else "health check FAILED"
            if "error_rate" in rec:
                desc += f" (error_rate={rec['error_rate']})"
            events.append(make_event(
                ts=ts, source="health", type="health_ok" if ok else "health_fail",
                service=rec.get("service", "unknown"), description=desc, attrs=attrs,
            ))
    return events

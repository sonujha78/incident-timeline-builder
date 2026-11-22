"""Incident window detection from service-level signals (health probes).

An incident opens after `start_consecutive` bad probes in a row and closes after
`recover_consecutive` good probes in a row. start/end are only as precise as the
probe interval, so the interval is stored on every Incident.
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Optional


@dataclass(frozen=True)
class Incident:
    service: str
    start: datetime                 # first bad probe of the incident
    detected_at: datetime           # when the start_consecutive-th bad probe arrived
    end: Optional[datetime]         # first good probe of the recovery; None = ongoing
    probe_count: int
    bad_probe_count: int
    peak_error_rate: float
    probe_interval_s: float         # accuracy of start/end is +/- this
    reason: str

    @property
    def ongoing(self):
        return self.end is None

    @property
    def duration_s(self):
        return None if self.end is None else (self.end - self.start).total_seconds()

    def to_dict(self):
        return {
            "service": self.service,
            "start": self.start.isoformat(),
            "detected_at": self.detected_at.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "ongoing": self.ongoing,
            "duration_s": self.duration_s,
            "probe_count": self.probe_count,
            "bad_probe_count": self.bad_probe_count,
            "peak_error_rate": self.peak_error_rate,
            "probe_interval_s": self.probe_interval_s,
            "reason": self.reason,
        }


def is_bad_probe(e, cfg):
    """A probe is bad if the check failed, error_rate is high, or latency is high."""
    if e.type == "health_fail":
        return True
    attrs = e.attrs or {}
    thr = float(cfg["error_rate_threshold"])
    er = attrs.get("error_rate")
    if thr > 0 and er is not None and float(er) >= thr:
        return True
    lat_thr = float(cfg.get("latency_ms_threshold", 0) or 0)
    lat = attrs.get("latency_ms")
    if lat_thr > 0 and lat is not None and float(lat) >= lat_thr:
        return True
    return False


def _scan(probes, cfg):
    need_bad = max(1, int(cfg["start_consecutive"]))
    need_good = max(1, int(cfg["recover_consecutive"]))
    found = []
    bad_run, good_run, cur = [], [], None
    for p in probes:
        bad = is_bad_probe(p, cfg)
        if cur is None:
            if bad:
                bad_run.append(p)
                if len(bad_run) >= need_bad:
                    cur = {"start": bad_run[0].ts, "detected": p.ts, "end": None}
                    good_run = []
            else:
                bad_run = []
        else:
            if bad:
                good_run = []
            else:
                good_run.append(p)
                if len(good_run) >= need_good:
                    cur["end"] = good_run[0].ts
                    found.append(cur)
                    cur, bad_run, good_run = None, [], []
    if cur is not None:
        found.append(cur)          # still ongoing, end stays None
    return found


def _merge_close(windows, gap_s):
    out = []
    for w in windows:
        prev = out[-1] if out else None
        if prev and prev["end"] is not None and \
                (w["start"] - prev["end"]).total_seconds() <= gap_s:
            prev["end"] = w["end"]
        else:
            out.append(dict(w))
    return out


def _drop_short(windows, min_s):
    keep = []
    for w in windows:
        if w["end"] is not None and (w["end"] - w["start"]).total_seconds() < min_s:
            continue
        keep.append(w)
    return keep


def _interval(probes):
    gaps = [(b.ts - a.ts).total_seconds() for a, b in zip(probes, probes[1:])]
    return round(median(gaps), 3) if gaps else 0.0


def _build(service, w, probes, cfg, interval):
    end = w["end"]
    inside = [p for p in probes
              if p.ts >= w["start"] and (end is None or p.ts < end)]
    bad = [p for p in inside if is_bad_probe(p, cfg)]
    peak = max((float(p.attrs.get("error_rate") or 0) for p in inside), default=0.0)
    reason = (f"{int(cfg['start_consecutive'])} consecutive bad probes "
              f"(failed check or error_rate >= {cfg['error_rate_threshold']})")
    if end is None:
        reason += "; no recovery seen yet"
    else:
        reason += f"; recovered after {int(cfg['recover_consecutive'])} consecutive good probes"
    return Incident(service=service, start=w["start"], detected_at=w["detected"],
                    end=end, probe_count=len(inside), bad_probe_count=len(bad),
                    peak_error_rate=peak, probe_interval_s=interval, reason=reason)


def detect_incidents(events, cfg):
    """cfg is the 'detection' section of the config. Returns a list of Incident."""
    by_service = {}
    for e in events:
        if e.source == "health" and e.type in ("health_ok", "health_fail"):
            by_service.setdefault(e.service, []).append(e)
    out = []
    for service in sorted(by_service):
        probes = sorted(by_service[service], key=lambda e: (e.ts, e.event_id))
        interval = _interval(probes)
        windows = _scan(probes, cfg)
        windows = _merge_close(windows, float(cfg["merge_gap_s"]))
        windows = _drop_short(windows, float(cfg["min_duration_s"]))
        out.extend(_build(service, w, probes, cfg, interval) for w in windows)
    return sorted(out, key=lambda i: (i.start, i.service))


def primary_incident(incidents):
    """The incident with the most bad probes (earlier one wins a tie)."""
    if not incidents:
        return None
    return max(incidents, key=lambda i: (i.bad_probe_count, -i.start.timestamp()))


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") + "Z"


def format_incident(i):
    end = _fmt(i.end) if i.end else "ONGOING (no recovery seen)"
    dur = f"{i.duration_s:.0f}s" if i.duration_s is not None else "n/a"
    return "\n".join([
        f"service        : {i.service}",
        f"start          : {_fmt(i.start)}",
        f"detected at    : {_fmt(i.detected_at)}",
        f"end            : {end}",
        f"duration       : {dur}",
        f"bad probes     : {i.bad_probe_count}/{i.probe_count}",
        f"peak error rate: {i.peak_error_rate}",
        f"accuracy       : +/- {i.probe_interval_s}s (one probe interval)",
        f"why            : {i.reason}",
    ])

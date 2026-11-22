"""Clock-skew correction.

Idea: one constant offset per source, estimated from anchor pairs (events in two
sources that describe the same moment). A constant offset fixes a wrong clock
without hiding real delays, because each event keeps its own gap to its anchor.
raw_ts is never lost and skew_applied_s is written on every event.
"""

from dataclasses import dataclass, replace
from datetime import timedelta
from statistics import median


@dataclass(frozen=True)
class SkewEstimate:
    source: str
    offset_s: float      # measured offset (seconds to add to the source clock)
    n_pairs: int
    spread_s: float      # max disagreement between anchor pairs
    applied: bool
    method: str          # reference | manual | auto | none
    reason: str

    @property
    def effective_offset_s(self):
        return self.offset_s if self.applied else 0.0

    def to_dict(self):
        return {"source": self.source, "offset_s": self.offset_s,
                "n_pairs": self.n_pairs, "spread_s": self.spread_s,
                "applied": self.applied, "method": self.method,
                "reason": self.reason}


def _raw(e):
    return e.raw_ts or e.ts


def _anchor_diffs(events, source, anchors, reference, max_offset_s):
    diffs = []
    for a in anchors:
        if a["source"] != source:
            continue
        lag = float(a.get("expected_lag_s", 0))
        ref_source = a.get("ref_source", reference)
        targets = sorted((e for e in events
                          if e.source == source and e.type == a["type"]),
                         key=lambda e: (_raw(e), e.event_id))
        refs = [e for e in events
                if e.source == ref_source and e.type == a["ref_type"]]
        used = set()
        for t in targets:
            best = None
            for r in refs:
                if r.service != t.service or r.event_id in used:
                    continue
                d = (_raw(r) - _raw(t)).total_seconds() - lag
                if abs(d) <= max_offset_s and (best is None or abs(d) < abs(best[0])):
                    best = (d, r)
            if best:
                used.add(best[1].event_id)
                diffs.append(best[0])
    return diffs


def estimate_source(events, source, clock_cfg):
    auto = clock_cfg["auto"]
    reference = clock_cfg["reference_source"]
    diffs = _anchor_diffs(events, source, auto["anchors"], reference,
                          float(auto["max_offset_s"]))
    if not diffs:
        return SkewEstimate(source, 0.0, 0, 0.0, False, "none",
                            "no anchor pairs found, clock left as is")
    off = round(median(diffs), 3)
    spread = round(max(abs(d - off) for d in diffs), 3)
    n = len(diffs)
    if n < int(auto["min_pairs"]):
        return SkewEstimate(source, off, n, spread, False, "auto",
                            f"only {n} anchor pair(s), need {auto['min_pairs']}; not corrected")
    if spread > float(auto["max_spread_s"]):
        return SkewEstimate(source, off, n, spread, False, "auto",
                            f"anchor offsets disagree (spread {spread}s > "
                            f"{auto['max_spread_s']}s); not corrected, order is uncertain")
    if abs(off) < float(auto["min_apply_s"]):
        return SkewEstimate(source, off, n, spread, False, "auto",
                            f"offset {off}s is within normal delay; left as is")
    return SkewEstimate(source, off, n, spread, True, "auto",
                        f"median of {n} anchor pairs, spread {spread}s")


def correct_clocks(events, clock_cfg):
    """Return (corrected_events, {source: SkewEstimate}). Input is not modified."""
    manual = clock_cfg.get("manual_skew_s") or {}
    reference = clock_cfg["reference_source"]
    estimates = {}
    for src in sorted({e.source for e in events}):
        if src == reference:
            estimates[src] = SkewEstimate(src, 0.0, 0, 0.0, False, "reference",
                                          "reference clock")
        elif src in manual:
            estimates[src] = SkewEstimate(src, float(manual[src]), 0, 0.0, True,
                                          "manual", "configured manual_skew_s")
        elif clock_cfg["auto"]["enabled"]:
            estimates[src] = estimate_source(events, src, clock_cfg)
        else:
            estimates[src] = SkewEstimate(src, 0.0, 0, 0.0, False, "none",
                                          "auto correction disabled")
    out = []
    for e in events:
        off = estimates[e.source].effective_offset_s
        out.append(replace(e, ts=_raw(e) + timedelta(seconds=off),
                           raw_ts=_raw(e), skew_applied_s=off))
    return out, estimates

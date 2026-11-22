"""Merge events from all sources into one deterministic, time-ordered timeline."""

from .clock import correct_clocks
from .events import SOURCES

_SOURCE_ORDER = {s: i for i, s in enumerate(SOURCES)}


def _key(e):
    return (e.ts, _SOURCE_ORDER.get(e.source, 99), e.type, e.service,
            e.description, e.event_id)


def merge(events):
    """Drop exact duplicates (same event_id) and sort. Same input set -> same output."""
    unique = {}
    for e in events:
        unique.setdefault(e.event_id, e)
    return sorted(unique.values(), key=_key)


def build_timeline(events, clock_cfg):
    """Correct clocks, then merge. Returns (timeline, skew_estimates)."""
    corrected, estimates = correct_clocks(events, clock_cfg)
    return merge(corrected), estimates


def format_timeline(events):
    lines = []
    for e in events:
        stamp = e.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"
        note = f"  [skew {e.skew_applied_s:+.1f}s]" if e.skew_applied_s else ""
        lines.append(f"{stamp}  {e.source:<7} {e.type:<11} {e.service:<8} "
                     f"{e.description}{note}")
    return "\n".join(lines)

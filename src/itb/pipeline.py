"""One entry point that runs the whole analysis on a list of events."""

from dataclasses import dataclass
from typing import Any

from .detect import detect_incidents, primary_incident
from .metrics import compute_metrics
from .rank import (assess_confidence, caveats_from_clocks, caveats_from_order,
                   rank_suspects)
from .timeline import build_timeline


@dataclass(frozen=True)
class Analysis:
    timeline: tuple
    estimates: dict
    incidents: tuple
    incident: Any = None       # the primary incident, or None
    ranking: Any = None
    confidence: Any = None
    metrics: Any = None
    caveats: tuple = ()        # clock warnings
    severe: tuple = ()         # event-order contradictions (force LOW confidence)


def analyze(events, cfg):
    """events: list[Event]. cfg: the full config dict. Same input -> same Analysis."""
    timeline, estimates = build_timeline(list(events), cfg["clock"])
    incidents = detect_incidents(timeline, cfg["detection"])
    incident = primary_incident(incidents)
    base = dict(timeline=tuple(timeline), estimates=estimates,
                incidents=tuple(incidents))
    if incident is None:
        return Analysis(**base)
    ranking = rank_suspects(timeline, incident, cfg["ranking"], cfg["detection"])
    caveats = tuple(caveats_from_clocks(estimates))
    severe = tuple(caveats_from_order(timeline, float(cfg["ranking"]["rollout_window_s"])))
    confidence = assess_confidence(ranking.suspects, cfg["ranking"], caveats, severe)
    top = ranking.suspects[0] if ranking.suspects else None
    return Analysis(**base, incident=incident, ranking=ranking, confidence=confidence,
                    metrics=compute_metrics(incident, top), caveats=caveats,
                    severe=severe)

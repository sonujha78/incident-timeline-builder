"""Suspect ranking: explainable, additive scoring of changes before an incident.

score (0-100) = proximity + change_type + relation + corroboration + evidence + stability

proximity      closer to the incident start = more points
change_type    deploy > config > restart (configurable)
relation       same service, or named in the affected service's error logs
corroboration  symptoms (error logs, abnormal exits) appeared after the change
evidence       direct failure signal on the change itself (OOM, non-zero exit)
stability      NEGATIVE: the service stayed healthy for a long time after the change

Every number is stored with a plain-text reason so a person can audit the ranking.
"""

import re
from dataclasses import dataclass

from .config import load_config
from .detect import is_bad_probe

CHANGE_TYPES = ("deploy", "config", "restart")
SELF_SYMPTOM_ACTIONS = ("die", "oom")     # the affected service dying is a symptom
ROLLOUT_ACTIONS = ("start", "restart")    # container (re)start after a deploy

TYPE_TEXT = {
    "deploy": "code change reached the service",
    "config": "configuration change",
    "restart": "container lifecycle event",
}


@dataclass(frozen=True)
class Component:
    name: str
    points: float
    max_points: float
    detail: str

    def to_dict(self):
        return {"name": self.name, "points": self.points,
                "max_points": self.max_points, "detail": self.detail}


@dataclass(frozen=True)
class Suspect:
    rank: int
    event: object
    score: float
    components: tuple
    lead_time_s: float      # seconds from the change to the incident start

    def to_dict(self):
        return {"rank": self.rank, "score": self.score,
                "lead_time_s": self.lead_time_s,
                "event": self.event.to_dict(),
                "components": [c.to_dict() for c in self.components]}


@dataclass(frozen=True)
class Ranking:
    suspects: tuple        # ranked, best first
    suppressed: tuple      # (event, reason) pairs: in the window but not suspects
    lookback_s: float


@dataclass(frozen=True)
class Confidence:
    level: str             # high | medium | low
    top_score: float
    margin: float
    reasons: tuple

    def to_dict(self):
        return {"level": self.level, "top_score": self.top_score,
                "margin": self.margin, "reasons": list(self.reasons)}


def _action(e):
    return str((e.attrs or {}).get("action", ""))


def _is_self_symptom(e, incident):
    return (e.type == "restart" and e.service == incident.service
            and _action(e) in SELF_SYMPTOM_ACTIONS)


def _rollout_of(e, changes, window_s):
    """If e is a container start right after a deploy/config, return that change."""
    if e.type != "restart" or _action(e) not in ROLLOUT_ACTIONS:
        return None
    best = None
    for c in changes:
        if c.service != e.service:
            continue
        gap = (e.ts - c.ts).total_seconds()
        if 0 <= gap <= window_s and (best is None or gap < best[0]):
            best = (gap, c)
    return best[1] if best else None


def _symptoms(events, incident, since, exclude_id):
    """Error logs and abnormal exits of the affected service, since..detected_at."""
    logs, exits = [], []
    for e in events:
        if e.event_id == exclude_id or e.service != incident.service:
            continue
        if not (since <= e.ts <= incident.detected_at):
            continue
        if e.type == "error_log":
            logs.append(e)
        elif _is_self_symptom(e, incident):
            exits.append(e)
    return logs, exits


def _relation(cand, incident, logs, max_points):
    if cand.service == incident.service:
        return Component("relation", max_points, max_points,
                         f"same service as the incident ({incident.service})")
    pat = re.compile(r"\b" + re.escape(cand.service) + r"\b", re.I)
    linked = [entry for entry in logs if pat.search(entry.description)]
    if linked:
        return Component("relation", max_points, max_points,
                         f"{len(linked)} error log(s) on {incident.service} "
                         f"mention '{cand.service}'")
    return Component("relation", 0.0, max_points,
                     f"different service ({cand.service}) and no error log "
                     f"links it to {incident.service}")


def _evidence(cand, max_points):
    if cand.type != "restart":
        return Component("evidence", 0.0, max_points,
                         "no direct failure signal on a code or config change")
    action = _action(cand)
    code = str((cand.attrs or {}).get("exit_code", ""))
    if action in ("oom", "kill") or (action == "die" and code not in ("", "0")):
        return Component("evidence", max_points, max_points,
                         f"abnormal container exit ({action}, exit code {code or 'n/a'})")
    if action == "stop":
        return Component("evidence", max_points / 2, max_points,
                         "container was stopped")
    return Component("evidence", 0.0, max_points,
                     f"container '{action or 'event'}' is not a failure by itself")


def _stability(cand, probes, incident, cfg, det):
    stable_s = float(cfg["stable_s"])
    penalty = float(cfg["stable_penalty"])
    between = [p for p in probes if cand.ts < p.ts < incident.start]
    if not between:
        return Component("stability", 0.0, 0.0,
                         "no probes between this change and the incident start")
    if any(is_bad_probe(p, det) for p in between):
        return Component("stability", 0.0, 0.0,
                         "failures were already visible after this change")
    span = (between[-1].ts - cand.ts).total_seconds()
    if span >= stable_s:
        return Component("stability", -penalty, 0.0,
                         f"service stayed healthy for {span:.0f}s after this change "
                         f"(>= {stable_s:.0f}s), so it is a weaker suspect")
    return Component("stability", 0.0, 0.0,
                     f"service was healthy for only {span:.0f}s after this change "
                     f"(< {stable_s:.0f}s)")


def _score(cand, events, probes, incident, cfg, det):
    w = cfg["weights"]
    lookback = float(cfg["lookback_s"])
    grace = float(incident.probe_interval_s)
    delta = (incident.start - cand.ts).total_seconds()
    comps = []

    prox_max = float(w["proximity"])
    pts = prox_max * max(0.0, 1.0 - max(0.0, delta) / lookback)
    if delta >= 0:
        detail = f"{delta:.0f}s before the incident start (lookback {lookback:.0f}s)"
    else:
        detail = (f"{-delta:.0f}s after the first bad probe, inside the "
                  f"+/-{grace:.0f}s probe tolerance")
    comps.append(Component("proximity", round(pts, 2), prox_max, detail))

    tw = cfg["type_weights"]
    comps.append(Component("change_type", float(tw.get(cand.type, 0)),
                           float(max(tw.values())), TYPE_TEXT.get(cand.type, cand.type)))

    logs, exits = _symptoms(events, incident, cand.ts, cand.event_id)
    comps.append(_relation(cand, incident, logs, float(w["relation"])))

    n = len(logs) + len(exits)
    cmax = float(w["corroboration"])
    comps.append(Component(
        "corroboration", round(cmax * min(n, 3) / 3, 2), cmax,
        f"{len(logs)} error log(s) and {len(exits)} abnormal exit(s) on "
        f"{incident.service} between this change and detection"))

    comps.append(_evidence(cand, float(w["evidence"])))
    comps.append(_stability(cand, probes, incident, cfg, det))

    total = sum(c.points for c in comps)
    return round(max(0.0, min(100.0, total)), 1), tuple(comps)


def rank_suspects(events, incident, cfg, detection_cfg=None):
    """events: corrected timeline. cfg: the 'ranking' config section."""
    det = detection_cfg or load_config()["detection"]
    lookback = float(cfg["lookback_s"])
    grace = float(incident.probe_interval_s)
    ordered = sorted(events, key=lambda e: (e.ts, e.event_id))
    changes = [e for e in ordered if e.type in ("deploy", "config")]
    probes = [e for e in ordered
              if e.source == "health" and e.service == incident.service
              and e.type in ("health_ok", "health_fail")]

    candidates, suppressed = [], []
    for e in ordered:
        if e.type not in CHANGE_TYPES:
            continue
        delta = (incident.start - e.ts).total_seconds()
        if not (-grace <= delta <= lookback):
            continue
        if _is_self_symptom(e, incident):
            suppressed.append((e, f"'{_action(e)}' of the affected service is a "
                                  f"symptom, not a cause"))
            continue
        parent = _rollout_of(e, changes, float(cfg["rollout_window_s"]))
        if parent is not None:
            suppressed.append((e, f"container start is the rollout of {parent.type} "
                                  f"'{parent.description}', not an independent cause"))
            continue
        candidates.append(e)

    scored = []
    for e in candidates:
        score, comps = _score(e, ordered, probes, incident, cfg, det)
        delta = (incident.start - e.ts).total_seconds()
        scored.append((score, delta, e, comps))
    scored.sort(key=lambda x: (-x[0], abs(x[1]), x[2].event_id))

    suspects = tuple(
        Suspect(rank=i, event=e, score=score, components=comps, lead_time_s=delta)
        for i, (score, delta, e, comps) in enumerate(scored, start=1))
    return Ranking(suspects=suspects, suppressed=tuple(suppressed), lookback_s=lookback)


def caveats_from_clocks(estimates):
    """Warnings for sources whose clock could not be corrected reliably."""
    out = []
    for src in sorted(estimates):
        est = estimates[src]
        if est.method == "auto" and not est.applied and "disagree" in est.reason:
            out.append(f"clock of '{src}' could not be corrected ({est.reason}); "
                       f"event order near the incident start may be wrong")
    return out


def assess_confidence(suspects, cfg, caveats=()):
    """Turn the ranking into an honest confidence level with reasons."""
    caveats = tuple(caveats)
    if not suspects:
        return Confidence("low", 0.0, 0.0, (
            "no change event in the lookback window before the incident; "
            "the cause cannot be determined from this data",) + caveats)
    cc = cfg["confidence"]
    hs, hm = float(cc["high_score"]), float(cc["high_margin"])
    ms, mm = float(cc["medium_score"]), float(cc["medium_margin"])
    top = suspects[0].score
    second = suspects[1].score if len(suspects) > 1 else 0.0
    margin = round(top - second, 1)

    reasons = [f"top suspect scored {top:.1f}/100"]
    if len(suspects) > 1:
        reasons.append(f"it leads the runner-up by {margin:.1f} points")
    else:
        reasons.append("it is the only candidate change in the window")

    if top >= hs and margin >= hm:
        level = "high"
        reasons.append(f"score >= {hs:g} and lead >= {hm:g}: clear winner")
    elif top >= ms and margin >= mm:
        level = "medium"
        reasons.append(f"score >= {ms:g} and lead >= {mm:g}, but not clear enough for high")
    else:
        level = "low"
        if top < ms:
            reasons.append(f"top score is below {ms:g}: weak evidence for any single change")
        else:
            reasons.append(f"lead is below {mm:g} points: the top suspects are too close to separate")

    if caveats:
        reasons.extend(caveats)
        if level == "high":
            level = "medium"
            reasons.append("downgraded from high because of the caveats above")
    return Confidence(level, top, margin, tuple(reasons))


def format_suspect(s):
    e = s.event
    lines = [f"#{s.rank}  score {s.score:.1f}/100  {e.type} ({e.source}) on {e.service} "
             f"at {e.ts.strftime('%H:%M:%S')}Z: {e.description}"]
    for c in s.components:
        lines.append(f"      {c.points:+6.1f} /{c.max_points:>4.0f}  {c.name:<13} {c.detail}")
    return "\n".join(lines)


def format_ranking(ranking, conf, top_n=5):
    shown = ranking.suspects[:top_n]
    lines = [f"candidate changes in the {ranking.lookback_s:.0f}s before the incident: "
             f"{len(ranking.suspects)} (showing top {len(shown)})"]
    if not shown:
        lines.append("  (none)")
    for s in shown:
        lines.append(format_suspect(s))
    if ranking.suppressed:
        lines.append("not treated as suspects:")
        for e, why in ranking.suppressed:
            lines.append(f"  - {e.ts.strftime('%H:%M:%S')}Z {e.type} on {e.service}: {why}")
    lines.append(f"confidence: {conf.level.upper()}  "
                 f"(top {conf.top_score:.1f}, lead {conf.margin:.1f})")
    for why in conf.reasons:
        lines.append(f"  - {why}")
    return "\n".join(lines)

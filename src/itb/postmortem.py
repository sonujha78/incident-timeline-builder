"""Postmortem draft generator (Markdown).

Deterministic: the report has no wall-clock time inside, so the same data and
config always give the same bytes. The whole text goes through redact() at the
end as a second layer of secret removal.
"""

from collections import Counter
from datetime import timedelta

from . import __version__
from .events import SOURCES
from .redact import redact

PROBE_TYPES = ("health_ok", "health_fail")
ABNORMAL_ACTIONS = ("die", "oom", "kill")


# ---------- small helpers ----------

def _ts(dt):
    return dt.strftime("%H:%M:%S") + "Z"


def _full(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") + "Z"


def _dur(seconds):
    if seconds is None:
        return "n/a"
    s = int(round(seconds))
    if s >= 60:
        return f"{s // 60}m {s % 60}s ({s}s)"
    return f"{s}s"


def _cell(text):
    """Make text safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def incident_id(inc):
    return f"inc-{inc.service}-{inc.start.strftime('%Y%m%dT%H%M%SZ')}"


def _window_end(a):
    inc = a.incident
    if inc.end is not None:
        return inc.end
    return max(e.ts for e in a.timeline)


def _in_window(inc, end, ts):
    return (inc.start <= ts < end) if inc.end is not None else (inc.start <= ts <= end)


def _data_line(a):
    counts = Counter(e.source for e in a.timeline)
    parts = ", ".join(f"{s} {counts[s]}" for s in SOURCES if counts.get(s))
    if not parts:
        return "Data: no events."
    return f"Data: {len(a.timeline)} events ({parts})."


def _lead_text(lead):
    if lead >= 0:
        return f"{lead:.0f}s before the incident start"
    return f"{-lead:.0f}s after the first bad probe (inside probe tolerance)"


# ---------- impact ----------

def _impact_stats(a, top_n):
    inc = a.incident
    end = _window_end(a)
    lo = inc.start - timedelta(seconds=inc.probe_interval_s)
    probes = [e for e in a.timeline
              if e.source == "health" and e.service == inc.service
              and e.type in PROBE_TYPES and _in_window(inc, end, e.ts)]
    rates = [float(e.attrs["error_rate"]) for e in probes
             if e.attrs and e.attrs.get("error_rate") is not None]
    errs = [e for e in a.timeline if e.type == "error_log" and lo <= e.ts <= end]
    own = Counter(e.description for e in errs if e.service == inc.service)
    other = Counter(e.service for e in errs if e.service != inc.service)
    life = [e for e in a.timeline if e.type == "restart"
            and e.service == inc.service and lo <= e.ts <= end]
    abnormal = [e for e in life if (e.attrs or {}).get("action") in ABNORMAL_ACTIONS]
    return {
        "avg_rate": (sum(rates) / len(rates)) if rates else None,
        "own_errors": sum(own.values()),
        "other_errors": sorted(other.items()),
        "top_msgs": sorted(own.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n],
        "lifecycle": len(life),
        "abnormal": len(abnormal),
    }


def _impact_section(a, cfg):
    inc, m = a.incident, a.metrics
    st = _impact_stats(a, int(cfg["report"]["top_error_messages"]))
    pct = (100.0 * inc.bad_probe_count / inc.probe_count) if inc.probe_count else 0.0
    rows = [
        ("Affected service", f"`{inc.service}`"),
        ("Incident start", f"{_full(inc.start)} (first bad probe)"),
        ("Detected", f"{_full(inc.detected_at)}"),
        ("Recovered", _full(inc.end) if inc.end else "not yet (ongoing)"),
        ("Duration", _dur(inc.duration_s) if inc.end else "n/a (ongoing)"),
        ("Time to detect (TTD)", _dur(m["ttd_s"])),
        ("Time to recover (TTR)", _dur(m["ttr_s"]) if inc.end else "n/a (ongoing)"),
        ("Bad health probes", f"{inc.bad_probe_count} of {inc.probe_count} ({pct:.0f}%)"),
        ("Peak error rate", f"{inc.peak_error_rate:g}"),
        ("Average error rate in window",
         "n/a" if st["avg_rate"] is None else f"{st['avg_rate']:.2f}"),
        ("Error log lines on this service", str(st["own_errors"])),
        ("Container events on this service",
         f"{st['lifecycle']} ({st['abnormal']} abnormal exit(s))"),
        ("Accuracy of start/end", f"+/- {inc.probe_interval_s:g}s (one probe interval)"),
    ]
    out = ["## Impact", "", "| Metric | Value |", "|---|---|"]
    out += [f"| {k} | {_cell(v)} |" for k, v in rows]
    out += ["", "TTD = first bad probe until the detection rule fired. "
                "TTR = first bad probe until the first good probe of the recovery. "
                "Both are measured on probes, so they are accurate to one probe interval.", ""]
    if st["top_msgs"]:
        out.append("Most frequent error lines:")
        out += [f"- {n} x `{msg}`" for msg, n in st["top_msgs"]]
        out.append("")
    if st["other_errors"]:
        out.append("Error lines on other services in the same window: " +
                   ", ".join(f"{svc} ({n})" for svc, n in st["other_errors"]) + ".")
        out.append("")
    return out


# ---------- timeline ----------

def _timeline_rows(a, cfg):
    inc = a.incident
    rep, rk = cfg["report"], cfg["ranking"]
    lo = inc.start - timedelta(seconds=float(rk["lookback_s"]))
    hi = _window_end(a) + timedelta(seconds=float(rep["after_window_s"]))
    ranked = {s.event.event_id: s.rank for s in a.ranking.suspects[: int(rk["top_n"])]}

    groups = []
    for e in a.timeline:
        if e.type in PROBE_TYPES or not (lo <= e.ts <= hi):
            continue
        key = (e.source, e.type, e.service, e.description)
        if groups and groups[-1]["key"] == key:
            groups[-1]["last"] = e.ts
            groups[-1]["n"] += 1
        else:
            groups.append({"key": key, "event": e, "last": e.ts, "n": 1})

    rows = []
    for g in groups:
        e = g["event"]
        notes = []
        rank = ranked.get(e.event_id)
        if rank:
            notes.append(f"suspect #{rank}")
        if e.skew_applied_s:
            notes.append(f"clock {e.skew_applied_s:+.0f}s, raw {_ts(e.raw_ts or e.ts)}")
        if g["n"] > 1:
            notes.append(f"x{g['n']} until {_ts(g['last'])}")
        rows.append({"ts": e.ts, "marker": False, "priority": bool(rank),
                     "source": e.source, "type": e.type, "service": e.service,
                     "text": e.description, "note": "; ".join(notes)})

    need = int(cfg["detection"]["start_consecutive"])
    marks = [(inc.start, "START", "Incident start (first bad probe)"),
             (inc.detected_at, "DETECTED", f"Detected ({need} bad probes in a row)")]
    if inc.end is not None:
        marks.append((inc.end, "RECOVERED", "Recovered (first good probe of the recovery)"))
    else:
        marks.append((_window_end(a), "NO RECOVERY", "No recovery seen in the data"))
    for ts, typ, text in marks:
        rows.append({"ts": ts, "marker": True, "priority": True, "source": "health",
                     "type": typ, "service": inc.service, "text": text, "note": ""})

    rows.sort(key=lambda r: (r["ts"], 0 if r["marker"] else 1, r["source"],
                             r["type"], r["service"], r["text"]))

    cap = int(rep["max_timeline_rows"])
    omitted = 0
    if len(rows) > cap:
        keep = [r for r in rows if r["priority"]]
        others = [r for r in rows if not r["priority"]]
        room = max(0, cap - len(keep))
        dropped = others[: max(0, len(others) - room)]
        omitted = len(dropped)
        gone = {id(r) for r in dropped}
        rows = [r for r in rows if id(r) not in gone]
    return rows, omitted


def _timeline_section(a, cfg):
    rows, omitted = _timeline_rows(a, cfg)
    look = float(cfg["ranking"]["lookback_s"])
    out = ["## Timeline", "",
           f"Times are UTC after clock correction, from {look:.0f}s before the incident "
           f"start until {float(cfg['report']['after_window_s']):.0f}s after recovery. "
           "Health probes are summarised by the START / DETECTED / RECOVERED rows; "
           "identical consecutive lines are collapsed.", "",
           "| Time (UTC) | Source | Type | Service | What happened | Note |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        text = f"**{_cell(r['text'])}**" if r["marker"] else _cell(r["text"])
        out.append(f"| {_ts(r['ts'])} | {r['source']} | {r['type']} | {r['service']} "
                   f"| {text} | {_cell(r['note'])} |")
    if omitted:
        out += ["", f"_{omitted} older event row(s) omitted to keep the table short "
                    "(they are in the collected data files)._"]
    out.append("")
    return out


# ---------- trigger ----------

def _max_text(c):
    if c.max_points:
        return f"{c.max_points:.0f}"
    return "penalty" if c.points < 0 else "-"


def _trigger_section(a, cfg):
    out = ["## Most likely trigger", ""]
    suspects = a.ranking.suspects
    conf = a.confidence
    look = float(cfg["ranking"]["lookback_s"])

    if not suspects:
        out += ["**No clear trigger.** No change event was recorded in the "
                f"{look:.0f}s before the incident start, so the tool cannot name a cause. "
                "This does not mean nothing changed; it means no change was visible "
                "in the collected sources.", ""]
    else:
        top = suspects[0]
        e = top.event
        attrs = e.attrs or {}
        if conf.level == "high":
            head = "**Most likely trigger (HIGH confidence):**"
        elif conf.level == "medium":
            head = "**Probable trigger (MEDIUM confidence). Treat it as a lead, not a fact:**"
        else:
            head = ("**No clear trigger (LOW confidence).** Best-scoring candidate, "
                    "shown as a lead only, not a conclusion:")
        out += [head, "",
                f"- **Change:** {e.type} from {e.source} on `{e.service}` at "
                f"{_full(e.ts)} ({_lead_text(top.lead_time_s)})",
                f"- **What:** {_cell(e.description)}"]
        if attrs.get("sha"):
            who = f" by {attrs['author']}" if attrs.get("author") else ""
            out.append(f"- **Commit:** `{attrs['sha']}`{who}")
        files = attrs.get("files") or []
        if files:
            more = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
            out.append("- **Files changed:** " + ", ".join(f"`{f}`" for f in files[:8]) + more)
        out.append(f"- **Score:** {top.score:.1f}/100")
        out += ["", "### Score breakdown (every point has a reason)", "",
                "| Component | Points | Max | Reason |", "|---|---|---|---|"]
        for c in top.components:
            out.append(f"| {c.name} | {c.points:+.1f} | {_max_text(c)} | {_cell(c.detail)} |")
        out.append("")
        rest = suspects[1: int(cfg["ranking"]["top_n"])]
        if rest:
            out += ["### Other candidates", "",
                    "| Rank | Score | Time | Type | Service | Change | Lead time |",
                    "|---|---|---|---|---|---|---|"]
            for s in rest:
                ev = s.event
                out.append(f"| #{s.rank} | {s.score:.1f} | {_ts(ev.ts)} | {ev.type} | "
                           f"{ev.service} | {_cell(ev.description)} | "
                           f"{s.lead_time_s:.0f}s |")
            out.append("")

    if a.ranking.suppressed:
        out += ["### Events that were not treated as suspects", ""]
        for ev, why in a.ranking.suppressed:
            out.append(f"- {_ts(ev.ts)} {ev.type} on `{ev.service}`: {why}")
        out.append("")
    return out


# ---------- confidence, clocks, next steps ----------

def _confidence_section(a):
    c = a.confidence
    out = ["## Confidence", "",
           f"**{c.level.upper()}** (top score {c.top_score:.1f}/100, "
           f"lead over the runner-up {c.margin:.1f} points)", ""]
    out += [f"- {r}" for r in c.reasons]
    out += ["", "_Scores are heuristic points (0-100), not probabilities. A high score "
                "means the change fits the timing and the symptoms, not that it is "
                "proven to be the cause._", ""]
    return out


def _clock_section(a):
    if not a.estimates:
        return []
    out = ["## Clock correction", "",
           "| Source | Method | Offset | Applied | Note |", "|---|---|---|---|---|"]
    for src in sorted(a.estimates):
        est = a.estimates[src]
        out.append(f"| {src} | {est.method} | {est.offset_s:+.1f}s | "
                   f"{'yes' if est.applied else 'no'} | {_cell(est.reason)} |")
    out += ["", "Each event keeps its raw time; a corrected event shows the correction "
                "in the Note column of the timeline.", ""]
    return out


def _next_steps(a, cfg):
    inc, conf = a.incident, a.confidence
    suspects = a.ranking.suspects
    steps = []
    if inc.ongoing:
        steps.append("The incident was still ongoing in this data: confirm the service "
                     "has really recovered before closing it.")
    if suspects:
        top = suspects[0]
        e = top.event
        attrs = e.attrs or {}
        if e.service != inc.service:
            steps.append(f"The top suspect is on `{e.service}`, not on `{inc.service}`: "
                         f"check the health and logs of `{e.service}` first.")
        if e.type == "deploy":
            sha = attrs.get("sha")
            ref = f" with `git show {sha}`" if sha else ""
            steps.append(f"Read the code change of the top suspect{ref}. Look for what "
                         f"could break `{inc.service}` (new dependency, protocol, "
                         "timeout, pool size).")
            steps.append("If the symptoms match the change, roll it back or hotfix it "
                         "and watch the next probes for recovery.")
        elif e.type == "config":
            steps.append("Diff the configuration change against the previous version "
                         "and find the setting on the failing path. Revert that one "
                         "setting to test it.")
        elif e.type == "restart":
            action = attrs.get("action")
            box = attrs.get("container", e.service)
            if action in ("oom", "kill"):
                steps.append(f"Check memory limits and usage of `{box}` (`docker inspect "
                             f"{box}` for OOMKilled, `docker stats`). Look for a leak or "
                             "a limit that is too low.")
            else:
                steps.append(f"Read the logs of `{box}` around {_ts(e.ts)} to see why it "
                             "stopped or restarted.")
        if conf.level != "high":
            steps.append(f"Confidence is {conf.level.upper()}: treat the top suspect as a "
                         "lead, not a fact. Look for evidence that separates it from the "
                         "alternatives, for example roll back only that change and watch "
                         "the probes.")
        if len(suspects) > 1:
            gap = suspects[0].score - suspects[1].score
            if gap < float(cfg["ranking"]["confidence"]["medium_margin"]):
                steps.append("Candidates #1 and #2 are too close to separate. Compare "
                             "what each one touched and test them one at a time.")
    else:
        steps.append("No change was recorded before the incident. Check what the tool "
                     "does not collect: infrastructure or cloud changes, a dependency's "
                     "own incident, a traffic spike, cron jobs, expired certificates, "
                     "disk or memory exhaustion.")
    if a.caveats or a.severe:
        steps.append("Fix time sync (NTP/chrony) on the sources named in the confidence "
                     "section and run the analysis again. Event order is unreliable "
                     "until then.")
    have = {e.source for e in a.timeline}
    missing = [s for s in SOURCES if s not in have]
    if missing:
        steps.append("No events were collected from: " + ", ".join(missing) +
                     ". Adding them gives the ranking more evidence.")
    steps.append("Once the real cause is known, write it in the last section and "
                 "compare it with this ranking. A wrong ranking is useful feedback.")
    return ["## What to check next", ""] + [f"{i}. {s}" for i, s in enumerate(steps, 1)] + [""]


def _human_section():
    return ["## To be completed by a human", "",
            "- Confirmed root cause: _TBD_",
            "- Fix or mitigation applied: _TBD_",
            "- Follow-up actions (owner, due date): _TBD_",
            "- Did the ranking above match the real cause? _TBD_", ""]


def _settings_section(cfg):
    d, r = cfg["detection"], cfg["ranking"]
    return ["## Settings used", "",
            f"- Detection: a probe is bad if the check failed or error_rate >= "
            f"{d['error_rate_threshold']}; an incident opens after "
            f"{d['start_consecutive']} bad probes in a row and closes after "
            f"{d['recover_consecutive']} good probes in a row.",
            f"- Ranking: changes up to {r['lookback_s']}s before the incident start "
            f"are candidates; confidence needs score >= {r['confidence']['high_score']} "
            f"and a lead of {r['confidence']['high_margin']} points for HIGH.",
            "- Reproduce: run the tool again on the same data and config to get this "
            "exact report.", ""]


# ---------- summary and assembly ----------

def _summary(a, cfg):
    inc, m, conf = a.incident, a.metrics, a.confidence
    if inc.end is not None:
        span = (f"from {_full(inc.start)} until {_full(inc.end)} "
                f"({_dur(inc.duration_s)})")
    else:
        span = f"from {_full(inc.start)} and was still ongoing at the end of the data"
    text = (f"Service `{inc.service}` was unhealthy {span}. "
            f"{inc.bad_probe_count} of {inc.probe_count} health probes in that window "
            f"were bad (peak error rate {inc.peak_error_rate:g}). "
            f"The incident was detected {_dur(m['ttd_s'])} after the first bad probe.")
    suspects = a.ranking.suspects
    look = float(cfg["ranking"]["lookback_s"])
    if not suspects:
        text += (f" No change was recorded in the {look:.0f}s before the incident, "
                 "so the tool cannot name a cause (confidence LOW).")
    else:
        top = suspects[0]
        e = top.event
        what = (f"{e.type} `{_cell(e.description)}` on `{e.service}` at {_ts(e.ts)}, "
                f"{_lead_text(top.lead_time_s)}")
        if conf.level == "high":
            text += f" The most likely trigger is the {what} (score {top.score:.1f}/100, confidence HIGH)."
        elif conf.level == "medium":
            text += (f" A probable trigger is the {what} (score {top.score:.1f}/100, "
                     "confidence MEDIUM). Treat it as a lead, not a fact.")
        else:
            text += (f" The tool has LOW confidence. The best-scoring candidate is the "
                     f"{what} (score {top.score:.1f}/100), but this is not enough to "
                     "call it the cause.")
    return ["## Summary", "", text, ""]


def _full_report(a, cfg):
    inc = a.incident
    out = [f"# Postmortem draft: `{inc.service}` incident {_full(inc.start)[:10]}", "",
           f"> **DRAFT** generated by Incident Timeline Builder v{__version__}. "
           f"Incident id: `{incident_id(inc)}`. {_data_line(a)} "
           "Numbers come from the collected data; the cause is a ranked hypothesis, "
           "not a verdict.", ""]
    out += _summary(a, cfg)
    out += _impact_section(a, cfg)
    out += _timeline_section(a, cfg)
    out += _trigger_section(a, cfg)
    out += _confidence_section(a)
    out += _clock_section(a)
    out += _next_steps(a, cfg)
    out += _human_section()
    out += _settings_section(cfg)
    return "\n".join(out)


def _no_incident(a, cfg):
    d = cfg["detection"]
    probes = [e for e in a.timeline if e.source == "health"]
    out = ["# Postmortem draft: no incident detected", "",
           f"> **DRAFT** generated by Incident Timeline Builder v{__version__}. "
           f"{_data_line(a)}", "", "## Summary", ""]
    if not probes:
        out.append("No incident could be detected because the data has no health probe "
                   "events. Detection needs a service-level signal (failed health "
                   "checks or an error rate).")
    else:
        out.append(f"No incident was detected in {len(probes)} health probes. There were "
                   f"never {d['start_consecutive']} bad probes in a row (a probe is bad "
                   f"if the check failed or error_rate >= {d['error_rate_threshold']}).")
    out += ["", "## What to check next", "",
            "1. If users did report a problem, check that the health probe covers the "
            "affected path.",
            "2. Consider lowering `error_rate_threshold` or `start_consecutive` in the "
            "config, then run the analysis again.", ""]
    out += _settings_section(cfg)
    return "\n".join(out)


def generate_postmortem(analysis, cfg):
    """Return the postmortem draft as Markdown text."""
    if analysis.incident is None:
        md = _no_incident(analysis, cfg)
    else:
        md = _full_report(analysis, cfg)
    return redact(md).rstrip() + "\n"

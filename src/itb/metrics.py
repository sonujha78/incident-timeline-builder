"""Time to detect / time to recover.

Both are measured on the probe signal, so each has an uncertainty of one probe interval.
"""


def compute_metrics(incident, suspect=None):
    ttd = (incident.detected_at - incident.start).total_seconds()
    ttr = incident.duration_s
    after = None if incident.end is None else \
        (incident.end - incident.detected_at).total_seconds()
    return {
        "ttd_s": ttd,                                   # first bad probe -> detection
        "ttr_s": ttr,                                   # first bad probe -> recovery
        "recovery_after_detection_s": after,            # detection -> recovery
        "change_to_impact_s": suspect.lead_time_s if suspect else None,
        "accuracy_s": incident.probe_interval_s,
    }


def _fmt(v, missing):
    return missing if v is None else f"{v:.0f}s"


def format_metrics(m):
    return "\n".join([
        "metrics:",
        f"  time to detect (TTD)    : {_fmt(m['ttd_s'], 'n/a')}"
        "   (first bad probe -> detection rule fired)",
        f"  time to recover (TTR)   : {_fmt(m['ttr_s'], 'n/a (still ongoing)')}"
        "   (first bad probe -> first good probe of the recovery)",
        f"  recovery after detection: {_fmt(m['recovery_after_detection_s'], 'n/a (still ongoing)')}",
        f"  change -> impact        : {_fmt(m['change_to_impact_s'], 'n/a (no suspect)')}",
        f"  accuracy                : +/- {m['accuracy_s']:g}s (one probe interval)",
    ])

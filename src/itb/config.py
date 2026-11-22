"""Config loading: built-in defaults merged with an optional YAML file."""

import copy
import re
from datetime import timedelta, timezone

import yaml

DEFAULTS = {
    "clock": {
        "reference_source": "docker",
        "source_tz": {},
        "manual_skew_s": {},
        "auto": {
            "enabled": True,
            "max_offset_s": 900,
            "max_spread_s": 10,
            "min_pairs": 2,
            "min_apply_s": 1.0,
            "anchors": [
                {"source": "git", "type": "deploy", "ref_source": "docker",
                 "ref_type": "restart", "expected_lag_s": 5},
            ],
        },
    },
    "detection": {
        "error_rate_threshold": 0.05,   # probe is bad if error_rate >= this
        "latency_ms_threshold": 0,      # 0 = latency is not used
        "start_consecutive": 3,         # bad probes in a row to open an incident
        "recover_consecutive": 3,       # good probes in a row to close it
        "min_duration_s": 10,           # shorter closed incidents are dropped
        "merge_gap_s": 30,              # incidents closer than this are merged
    },
    "ranking": {
        "lookback_s": 600,              # how far before the incident start to look
        "top_n": 5,                     # how many suspects reports show
        "weights": {
            "proximity": 40,
            "relation": 15,
            "corroboration": 15,
            "evidence": 10,
        },
        "type_weights": {"deploy": 20, "config": 15, "restart": 8},
        "stable_s": 60,                 # healthy this long after a change = weaker suspect
        "stable_penalty": 25,
        "rollout_window_s": 60,         # container start this soon after a deploy = rollout
        "confidence": {
            "high_score": 70,
            "high_margin": 15,
            "medium_score": 50,
            "medium_margin": 8,
        },
    },
    "report": {
        "max_timeline_rows": 40,        # keep the timeline table short
        "after_window_s": 60,           # show events this long after recovery
        "top_error_messages": 3,        # most frequent error lines in Impact
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict) and val:
            out[key] = _merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def load_config(path=None):
    """Return defaults, overridden by the YAML file at path (if given)."""
    if not path:
        return copy.deepcopy(DEFAULTS)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return _merge(DEFAULTS, data)


_TZ = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def parse_tz(text):
    """'UTC' / 'Z' / '+05:30' / '-0800' -> datetime.timezone."""
    s = str(text).strip()
    if s.upper() in ("", "UTC", "Z"):
        return timezone.utc
    m = _TZ.match(s)
    if not m:
        raise ValueError(f"bad timezone: {text!r}")
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    return timezone(delta if m.group(1) == "+" else -delta)

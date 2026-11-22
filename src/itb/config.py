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

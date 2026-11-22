"""Common event format. Every collector must return a list of Event."""

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .redact import redact, redact_obj

# Allowed event types. Keep this small and meaningful.
EVENT_TYPES = (
    "deploy",       # code or config change reached the service
    "restart",      # container/pod restarted, killed, OOM
    "config",       # config / env / flag change
    "error_log",    # application error line
    "health_fail",  # failed health probe
    "health_ok",    # successful health probe
    "metric",       # numeric sample (error rate, latency, memory)
    "info",         # anything else
)

SOURCES = ("git", "docker", "applog", "health")


def parse_ts(value, assume_tz=timezone.utc):
    """Parse ISO-8601 text or epoch seconds into an aware UTC datetime.

    Naive timestamps are interpreted in assume_tz (the source's declared zone).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Event:
    ts: datetime                 # corrected UTC time (used for ordering)
    source: str                  # git | docker | applog | health
    type: str                    # one of EVENT_TYPES
    service: str                 # affected service name
    description: str             # short, already redacted
    raw_ts: datetime = None      # time as the source reported it (UTC-normalised)
    skew_applied_s: float = 0.0  # correction added to raw_ts (seconds)
    attrs: dict = field(default_factory=dict)  # extra data, already redacted
    event_id: str = ""

    def to_dict(self):
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        d["raw_ts"] = (self.raw_ts or self.ts).isoformat()
        return d


def make_event(ts, source, type, service, description, attrs=None,
               raw_ts=None, skew_applied_s=0.0):
    """Build a validated, redacted Event with a deterministic event_id."""
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type!r}")
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source!r}")
    ts = parse_ts(ts)
    raw = parse_ts(raw_ts) if raw_ts is not None else ts
    desc = redact(str(description))[:300]
    clean_attrs = redact_obj(attrs or {})
    key = "|".join([raw.isoformat(), source, type, service, desc])
    event_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return Event(ts=ts, source=source, type=type, service=service,
                 description=desc, raw_ts=raw, skew_applied_s=skew_applied_s,
                 attrs=clean_attrs, event_id=event_id)


def event_from_dict(d):
    """Rebuild an Event from to_dict() output (used when replaying files)."""
    return make_event(
        ts=d["ts"], source=d["source"], type=d["type"], service=d["service"],
        description=d["description"], attrs=d.get("attrs"),
        raw_ts=d.get("raw_ts"), skew_applied_s=d.get("skew_applied_s", 0.0),
    )

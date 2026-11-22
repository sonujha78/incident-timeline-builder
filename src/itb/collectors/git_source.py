"""Git / deploy collector. Reads git.jsonl (one JSON object per line)."""

import json

from ..events import make_event, parse_ts

CONFIG_HINTS = (".env", ".yaml", ".yml", ".toml", ".ini", ".conf", "config")


def _classify(record):
    """deploy for code changes, config for config-only changes."""
    explicit = record.get("kind")
    if explicit in ("deploy", "config"):
        return explicit
    files = record.get("files") or []
    if files and all(any(h in f.lower() for h in CONFIG_HINTS) for f in files):
        return "config"
    return "deploy"


def collect(path, tz=None):
    """Return a list of Event from a git.jsonl file."""
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ts = parse_ts(rec["ts"], assume_tz=tz) if tz else parse_ts(rec["ts"])
            sha = str(rec.get("sha", ""))[:7]
            msg = rec.get("message", "")
            events.append(make_event(
                ts=ts, source="git", type=_classify(rec),
                service=rec.get("service", "unknown"),
                description=f"{sha} {msg}".strip(),
                attrs={"sha": sha, "author": rec.get("author", ""),
                       "files": rec.get("files", [])},
            ))
    return events

"""Helpers for recording collected data. Every line is redacted BEFORE it is stored."""

import hashlib
import json
from datetime import datetime, timezone

from .redact import redact, redact_obj


def iso(ts):
    """Epoch seconds -> ISO-8601 UTC text with milliseconds."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


def fake_sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def git_record(ts, message, service, files, author="demo-dev", skew_s=0.0, kind=None):
    """One git.jsonl record. skew_s simulates a git clock that is ahead (+) or behind (-)."""
    rec = {"ts": iso(ts + skew_s), "sha": fake_sha(f"{service}:{message}"),
           "author": author, "message": message, "service": service,
           "files": list(files)}
    if kind:
        rec["kind"] = kind
    return redact_obj(rec)


def dump_jsonl_line(obj):
    """Redact every string inside obj, then dump as one compact JSON line."""
    return json.dumps(redact_obj(obj), sort_keys=True, separators=(",", ":"))


def redact_log_text(text):
    """Redact a multi-line log, line by line."""
    return "".join(redact(line) for line in text.splitlines(keepends=True))

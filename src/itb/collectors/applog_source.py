"""Application log collector. Reads app.log lines like:

2026-01-01 10:00:05,123 ERROR web: connection refused to db:5432
"""

import re
from datetime import timezone

from ..events import make_event, parse_ts

LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"(?P<level>[A-Z]+)\s+(?P<service>[\w.-]+):\s*(?P<msg>.*)$"
)
ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"}
INFO_LEVELS = {"INFO", "NOTICE"}   # kept as type "info": a process that dies cannot log errors


def collect(path, tz=None):
    """tz = timezone this log's naive timestamps are written in."""
    events = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = LINE.match(line.strip())
            if not m:
                continue
            level = m.group("level")
            if level in ERROR_LEVELS:
                etype = "error_log"
            elif level in INFO_LEVELS:
                etype = "info"
            else:
                continue
            ts = parse_ts(m.group("ts").replace(",", "."), assume_tz=tz or timezone.utc)
            events.append(make_event(
                ts=ts, source="applog", type=etype,
                service=m.group("service"), description=m.group("msg"),
                attrs={"level": level},
            ))
    return events

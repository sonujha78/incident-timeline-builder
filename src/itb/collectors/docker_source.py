"""Docker events collector. Reads docker.jsonl from `docker events --format '{{json .}}'`."""

import json

from ..events import make_event, parse_ts

# Docker actions we care about -> event type
_RESTART_ACTIONS = {"start", "restart", "die", "kill", "oom", "stop"}


def collect(path, tz=None):
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("Type", "container") != "container":
                continue
            action = str(rec.get("Action") or rec.get("status") or "").split(":")[0]
            if action not in _RESTART_ACTIONS:
                continue
            actor = rec.get("Actor", {}) or {}
            attrs = actor.get("Attributes", {}) or {}
            name = attrs.get("name", "unknown")
            service = attrs.get("com.docker.compose.service") or name.replace("itb-", "", 1)
            # docker gives epoch seconds in "time" / nanoseconds in "timeNano"
            raw = rec.get("timeNano")
            ts = parse_ts(float(raw) / 1e9) if raw else parse_ts(rec["time"])
            extra = {"container": name, "action": action}
            desc = f"container {name} {action}"
            if action == "die":
                code = attrs.get("exitCode", "?")
                extra["exit_code"] = code
                desc += f" (exit {code})"
            if action == "oom":
                desc = f"container {name} OOM killed"
            events.append(make_event(ts=ts, source="docker", type="restart",
                                     service=service, description=desc, attrs=extra))
    return events

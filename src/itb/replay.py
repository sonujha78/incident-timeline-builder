"""Load a recorded incident directory (git.jsonl, docker.jsonl, app.log, health.jsonl)."""

import json
from pathlib import Path

from .collectors import collect_source
from .config import load_config, parse_tz

FILES = {"git": "git.jsonl", "docker": "docker.jsonl",
         "applog": "app.log", "health": "health.jsonl"}


def load_meta(data_dir):
    p = Path(data_dir) / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_events(data_dir, cfg=None):
    """Read every source file that exists. Timezones: config wins over meta.json."""
    cfg = cfg or load_config(None)
    data_dir = Path(data_dir)
    tzmap = {**load_meta(data_dir).get("source_tz", {}),
             **(cfg["clock"].get("source_tz") or {})}
    events = []
    for source, filename in FILES.items():
        path = data_dir / filename
        if path.exists():
            events.extend(collect_source(source, str(path),
                                         tz=parse_tz(tzmap.get(source, "UTC"))))
    return events

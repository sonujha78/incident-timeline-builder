"""Collectors: one module per event source.

To add a new source: write a module with collect(path, tz=None) -> list[Event]
and register it in COLLECTORS below.
"""

from . import applog_source, docker_source, git_source, health_source

COLLECTORS = {
    "git": git_source.collect,
    "docker": docker_source.collect,
    "applog": applog_source.collect,
    "health": health_source.collect,
}


def collect_source(name, path, tz=None):
    if name not in COLLECTORS:
        raise ValueError(f"unknown source: {name!r}")
    return COLLECTORS[name](path, tz=tz)

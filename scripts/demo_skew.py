"""Shows raw order vs corrected order when the git clock is 60s ahead."""

from itb.config import load_config
from itb.events import make_event
from itb.timeline import build_timeline, format_timeline, merge

E = make_event
events = [
    E("2026-01-01T10:01:00Z", "git", "deploy", "web", "abc1234 bump pool size"),
    E("2026-01-01T10:00:05Z", "docker", "restart", "web", "container itb-web start"),
    E("2026-01-01T10:00:20Z", "applog", "error_log", "web", "connection pool exhausted"),
    E("2026-01-01T10:00:30Z", "health", "health_fail", "web", "health check FAILED"),
    E("2026-01-01T10:11:00Z", "git", "deploy", "web", "def5678 tune timeout"),
    E("2026-01-01T10:10:05Z", "docker", "restart", "web", "container itb-web start"),
]

clock = load_config()["clock"]
print("=== RAW ORDER (skewed clocks) ===")
print(format_timeline(merge(events)))
timeline, est = build_timeline(events, clock)
print("\n=== CORRECTED TIMELINE ===")
print(format_timeline(timeline))
print("\n=== SKEW REPORT ===")
for src, s in est.items():
    print(f"{src:<7} applied={s.applied!s:<5} offset={s.offset_s:+.1f}s  {s.reason}")

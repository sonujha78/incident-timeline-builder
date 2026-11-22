import json
from pathlib import Path

from itb.collectors import collect_source
from itb.config import load_config
from itb.replay import load_events


def make_dir(tmp_path):
    (tmp_path / "git.jsonl").write_text(json.dumps(
        {"ts": "2026-01-01T10:01:00Z", "sha": "abc1234def", "message": "deploy v2",
         "service": "web", "files": ["app/x.py"]}) + "\n")
    (tmp_path / "docker.jsonl").write_text(json.dumps(
        {"Type": "container", "Action": "start", "timeNano": 1767261605000000000,
         "Actor": {"Attributes": {"name": "itb-web",
                                  "com.docker.compose.service": "web"}}}) + "\n")
    (tmp_path / "app.log").write_text("2026-01-01 15:30:20,000 ERROR web: boom\n")
    (tmp_path / "health.jsonl").write_text(json.dumps(
        {"ts": "2026-01-01T10:00:00Z", "service": "web", "ok": True}) + "\n")
    (tmp_path / "meta.json").write_text(json.dumps({"source_tz": {"applog": "+05:30"}}))
    return tmp_path


def applog_ts(events):
    return [e for e in events if e.source == "applog"][0].ts.isoformat()


def test_load_events_reads_all_sources_and_uses_meta_timezone(tmp_path):
    events = load_events(make_dir(tmp_path))
    assert {e.source for e in events} == {"git", "docker", "applog", "health"}
    assert applog_ts(events) == "2026-01-01T10:00:20+00:00"     # IST -> UTC


def test_config_timezone_wins_over_meta(tmp_path):
    cfg = load_config(None)
    cfg["clock"]["source_tz"] = {"applog": "UTC"}
    assert applog_ts(load_events(make_dir(tmp_path), cfg)) == "2026-01-01T15:30:20+00:00"


def test_applog_without_timezone_is_read_as_utc_not_local_time(tmp_path):
    p = make_dir(tmp_path) / "app.log"
    ev = collect_source("applog", str(p))[0]
    assert ev.ts.isoformat() == "2026-01-01T15:30:20+00:00"


def test_demo_config_overrides_and_keeps_defaults():
    cfg = load_config(str(Path(__file__).resolve().parents[1] / "config" / "demo.yaml"))
    assert cfg["clock"]["source_tz"]["applog"] == "+05:30"
    assert cfg["clock"]["auto"]["anchors"][0]["expected_lag_s"] == 2
    assert cfg["ranking"]["start_grace_s"] == 3
    assert cfg["detection"]["start_consecutive"] == 3

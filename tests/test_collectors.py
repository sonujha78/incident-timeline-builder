import json
from datetime import timezone, timedelta

import pytest

from itb.collectors import collect_source
from itb.collectors import applog_source

IST = timezone(timedelta(hours=5, minutes=30))


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_git_deploy_and_config(tmp_path):
    rows = [
        {"ts": "2026-01-01T10:00:00Z", "sha": "abcdef1234", "message": "add cache",
         "service": "web", "files": ["app/main.py"]},
        {"ts": "2026-01-01T10:05:00Z", "sha": "1234567890", "message": "tune pool",
         "service": "web", "files": ["config/app.yaml"]},
    ]
    p = write(tmp_path, "git.jsonl", "\n".join(json.dumps(r) for r in rows))
    evs = collect_source("git", p)
    assert [e.type for e in evs] == ["deploy", "config"]
    assert evs[0].description.startswith("abcdef1")


def test_git_secret_in_message_is_redacted(tmp_path):
    row = {"ts": "2026-01-01T10:00:00Z", "sha": "abc1234", "service": "web",
           "message": "set DB password=hunter2", "files": []}
    p = write(tmp_path, "git.jsonl", json.dumps(row))
    assert "hunter2" not in collect_source("git", p)[0].description


def test_docker_die_and_oom(tmp_path):
    rows = [
        {"Type": "container", "Action": "die", "timeNano": 1767261600000000000,
         "Actor": {"Attributes": {"name": "itb-web", "exitCode": "137"}}},
        {"Type": "container", "Action": "oom", "time": 1767261601,
         "Actor": {"Attributes": {"name": "itb-web"}}},
        {"Type": "network", "Action": "connect", "time": 1767261602, "Actor": {}},
    ]
    p = write(tmp_path, "docker.jsonl", "\n".join(json.dumps(r) for r in rows))
    evs = collect_source("docker", p)
    assert len(evs) == 2
    assert evs[0].service == "web"
    assert evs[0].attrs["exit_code"] == "137"
    assert "OOM" in evs[1].description


def test_applog_parses_errors_and_applies_source_tz(tmp_path):
    text = (
        "2026-01-01 15:30:00,500 INFO web: all good\n"
        "2026-01-01 15:30:05,250 ERROR web: connection refused to db:5432\n"
        "garbage line\n"
    )
    p = write(tmp_path, "app.log", text)
    evs = applog_source.collect(p, tz=IST)
    assert [e.type for e in evs] == ["info", "error_log"]   # garbage skipped
    assert evs[1].ts.isoformat() == "2026-01-01T10:00:05.250000+00:00"


def test_health_ok_and_fail(tmp_path):
    rows = [
        {"ts": "2026-01-01T10:00:00Z", "service": "web", "ok": True, "latency_ms": 20},
        {"ts": "2026-01-01T10:00:05Z", "service": "web", "ok": False, "error_rate": 0.6},
    ]
    p = write(tmp_path, "health.jsonl", "\n".join(json.dumps(r) for r in rows))
    evs = collect_source("health", p)
    assert [e.type for e in evs] == ["health_ok", "health_fail"]
    assert "error_rate=0.6" in evs[1].description


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        collect_source("nope", "x")

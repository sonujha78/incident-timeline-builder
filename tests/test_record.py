import json

from itb.record import dump_jsonl_line, fake_sha, git_record, redact_log_text


def test_git_record_applies_skew_and_redacts_message():
    rec = git_record(1767261600, "fix, token=demo-token-abc123xyz", "web", ["a.py"], skew_s=60)
    assert rec["ts"] == "2026-01-01T10:01:00.000+00:00"
    assert "demo-token-abc123xyz" not in json.dumps(rec)
    assert rec["service"] == "web"


def test_sha_is_deterministic():
    assert fake_sha("web:x") == fake_sha("web:x")
    assert fake_sha("web:x") != fake_sha("web:y")
    assert len(fake_sha("x")) == 40


def test_jsonl_line_redacts_nested_values_and_stays_valid_json():
    line = dump_jsonl_line({"a": {"url": "postgres://app:Demo-S3cret-pw@db/x"}, "n": 1})
    assert "Demo-S3cret-pw" not in line
    assert json.loads(line)["n"] == 1


def test_log_text_is_redacted_line_by_line():
    out = redact_log_text("ok line\nERROR web: login password=Demo-S3cret-pw failed\n")
    assert "Demo-S3cret-pw" not in out
    assert out.count("\n") == 2

import json
import shutil
from pathlib import Path

from itb.cli import main

ROOT = Path(__file__).resolve().parents[1]
DEMO_CFG = str(ROOT / "config" / "demo.yaml")
BAD = ROOT / "data" / "incidents" / "bad_deploy"


def test_analyze_gives_identical_bytes_on_repeat(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    assert main(["analyze", str(BAD), "--config", DEMO_CFG, "--out", str(a)]) == 0
    assert main(["analyze", str(BAD), "--config", DEMO_CFG, "--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes() and a.stat().st_size > 1000


def test_analyze_json_is_valid_and_has_the_answer(capsys):
    assert main(["analyze", str(BAD), "--config", DEMO_CFG, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["confidence"]["level"] == "high"
    assert "switch to new db driver" in data["suspects"][0]["description"]
    assert data["metrics"]["ttd_s"] > 0


def test_check_passes_on_recordings_and_writes_markdown(tmp_path, capsys):
    md = tmp_path / "results.md"
    code = main(["check", "--root", str(ROOT / "data" / "incidents"),
                 "--config", DEMO_CFG, "--markdown", str(md)])
    out = capsys.readouterr().out
    assert code == 0 and "4/4 incidents passed" in out
    assert "| bad_deploy |" in md.read_text(encoding="utf-8")


def tampered(tmp_path, **changes):
    d = tmp_path / "bad_deploy"
    shutil.copytree(BAD, d)
    p = d / "ground_truth.json"
    gt = json.loads(p.read_text(encoding="utf-8"))
    gt.update(changes)
    p.write_text(json.dumps(gt), encoding="utf-8")
    return d


def test_check_fails_when_the_start_time_is_wrong(tmp_path):
    d = tampered(tmp_path, true_start="2020-01-01T00:00:00+00:00")
    assert main(["check", str(d), "--config", DEMO_CFG]) == 1


def test_check_fails_when_the_cause_is_wrong(tmp_path):
    d = tampered(tmp_path, cause={"type": "deploy", "service": "web", "match": "does not exist"})
    assert main(["check", str(d), "--config", DEMO_CFG]) == 1

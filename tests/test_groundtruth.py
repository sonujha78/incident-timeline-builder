from pathlib import Path

import pytest

from itb.config import load_config
from itb.groundtruth import check_case

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(str(ROOT / "config" / "demo.yaml"))
ALL = ["bad_deploy", "failing_dependency", "resource_exhaustion", "no_clear_cause"]
WITH_CAUSE = ["bad_deploy", "failing_dependency", "resource_exhaustion"]


def run(name):
    return check_case(ROOT / "data" / "incidents" / name, CFG)


@pytest.mark.parametrize("name", ALL)
def test_recorded_incident_passes_all_checks(name):
    r = run(name)
    assert r.passed, [f"{c.name}: {c.detail}" for c in r.checks if not c.passed]


@pytest.mark.parametrize("name", WITH_CAUSE)
def test_known_cause_is_ranked_first(name):
    assert run(name).cause_rank == 1


def test_no_cause_incident_is_low_confidence():
    r = run("no_clear_cause")
    assert not r.has_cause and r.confidence == "LOW"

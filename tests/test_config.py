from datetime import timezone, timedelta

import pytest

from itb.config import load_config, parse_tz


def test_defaults_when_no_file():
    cfg = load_config(None)
    assert cfg["clock"]["reference_source"] == "docker"
    assert cfg["clock"]["auto"]["min_pairs"] == 2


def test_yaml_overrides_merge_with_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("clock:\n  reference_source: git\n  auto:\n    min_pairs: 3\n")
    cfg = load_config(str(p))
    assert cfg["clock"]["reference_source"] == "git"
    assert cfg["clock"]["auto"]["min_pairs"] == 3
    assert cfg["clock"]["auto"]["max_spread_s"] == 10      # default kept
    assert cfg["clock"]["auto"]["anchors"]                  # default kept


def test_parse_tz():
    assert parse_tz("UTC") == timezone.utc
    assert parse_tz("+05:30") == timezone(timedelta(hours=5, minutes=30))
    assert parse_tz("-0800") == timezone(-timedelta(hours=8))
    with pytest.raises(ValueError):
        parse_tz("IST")

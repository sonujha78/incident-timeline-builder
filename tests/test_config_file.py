from pathlib import Path

from itb.config import load_config


def test_shipped_yaml_matches_built_in_defaults():
    path = Path(__file__).resolve().parents[1] / "config" / "itb.yaml"
    assert load_config(str(path)) == load_config(None)

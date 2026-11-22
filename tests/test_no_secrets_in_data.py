from pathlib import Path

SECRETS = ["Demo-S3cret-pw", "demo-token-abc123xyz", "demo-key-98765"]
ROOT = Path(__file__).resolve().parents[1]


def test_no_demo_secret_in_recorded_data_or_reports():
    leaks = []
    for base in ("data/incidents", "docs/examples", "reports"):
        for p in (ROOT / base).rglob("*"):
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="ignore")
                leaks += [f"{p.relative_to(ROOT)}: {s}" for s in SECRETS if s in text]
    assert leaks == []

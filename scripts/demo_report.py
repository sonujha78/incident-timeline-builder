"""Writes two example postmortem drafts into docs/examples/."""

from pathlib import Path

from demo_rank import build_events          # same demo data as the ranking demo
from itb.config import load_config
from itb.pipeline import analyze
from itb.postmortem import generate_postmortem

OUT = Path("docs/examples")


def main():
    cfg = load_config("config/itb.yaml")
    OUT.mkdir(parents=True, exist_ok=True)

    events = build_events()                  # git clock is 60s ahead on purpose
    md = generate_postmortem(analyze(events, cfg), cfg)
    (OUT / "bad_deploy_postmortem.md").write_text(md, encoding="utf-8")
    print(md)

    no_change = [e for e in events if e.type not in ("deploy", "config", "restart")]
    md2 = generate_postmortem(analyze(no_change, cfg), cfg)
    (OUT / "no_cause_postmortem.md").write_text(md2, encoding="utf-8")
    print(f"\nwritten: {OUT / 'bad_deploy_postmortem.md'}")
    print(f"written: {OUT / 'no_cause_postmortem.md'}")


if __name__ == "__main__":
    main()

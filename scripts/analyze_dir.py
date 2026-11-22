"""Analyse a recorded incident directory and print (or save) the postmortem draft.

python scripts/analyze_dir.py data/incidents/bad_deploy --config config/demo.yaml --out reports/bad_deploy.md
"""
import argparse
from pathlib import Path

from itb.config import load_config
from itb.pipeline import analyze
from itb.postmortem import generate_postmortem
from itb.replay import load_events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--config", default="config/itb.yaml")
    ap.add_argument("--out")
    args = ap.parse_args()
    cfg = load_config(args.config)
    md = generate_postmortem(analyze(load_events(args.data_dir, cfg), cfg), cfg)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()

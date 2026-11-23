"""Command line: `itb analyze DIR` and `itb check`."""

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .groundtruth import check_case, format_details, format_markdown, format_table
from .pipeline import analyze
from .postmortem import generate_postmortem
from .replay import load_events


def summary(a):
    """Small machine-readable summary of an Analysis (deterministic)."""
    ranking = a.ranking
    return {
        "events": len(a.timeline),
        "incident": a.incident.to_dict() if a.incident else None,
        "confidence": a.confidence.to_dict() if a.confidence else None,
        "metrics": a.metrics,
        "clock": {k: v.to_dict() for k, v in sorted(a.estimates.items())},
        "suspects": [{"rank": s.rank, "score": s.score, "type": s.event.type,
                      "service": s.event.service, "description": s.event.description,
                      "lead_time_s": s.lead_time_s}
                     for s in (ranking.suspects[:5] if ranking else [])],
    }


def cmd_analyze(args):
    cfg = load_config(args.config)
    a = analyze(load_events(args.data_dir, cfg), cfg)
    if args.json:
        text = json.dumps(summary(a), indent=2, sort_keys=True) + "\n"
    else:
        text = generate_postmortem(a, cfg)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_check(args):
    cfg = load_config(args.config)
    root = Path(args.root)
    dirs = [Path(d) for d in args.dirs]
    if not dirs and root.is_dir():
        dirs = sorted(p for p in root.iterdir() if (p / "ground_truth.json").exists())
    if not dirs:
        print("no recorded incidents found", file=sys.stderr)
        return 2
    results = [check_case(d, cfg) for d in dirs]
    print(format_table(results))
    details = format_details(results, verbose=args.verbose)
    if details:
        print("\n" + details)
    if args.markdown:
        Path(args.markdown).write_text(format_markdown(results), encoding="utf-8")
        print(f"\nwritten: {args.markdown}")
    failed = [r.name for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} incidents passed"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def build_parser():
    ap = argparse.ArgumentParser(prog="itb", description="Incident Timeline Builder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse a recorded incident directory")
    a.add_argument("data_dir")
    a.add_argument("--config", default="config/itb.yaml")
    a.add_argument("--out", help="write the report to this file")
    a.add_argument("--json", action="store_true", help="short JSON summary instead of Markdown")
    a.set_defaults(func=cmd_analyze)
    c = sub.add_parser("check", help="check recorded incidents against their ground truth")
    c.add_argument("dirs", nargs="*", help="incident directories (default: all under --root)")
    c.add_argument("--root", default="data/incidents")
    c.add_argument("--config", default="config/demo.yaml")
    c.add_argument("--markdown", help="also write the result table as Markdown")
    c.add_argument("-v", "--verbose", action="store_true", help="show every check")
    c.set_defaults(func=cmd_check)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

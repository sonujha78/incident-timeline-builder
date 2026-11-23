"""Compare the tool's result on a recorded incident with its known cause (ground truth)."""

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .events import parse_ts
from .pipeline import analyze
from .postmortem import generate_postmortem
from .replay import load_events

DEMO_SECRETS = ("Demo-S3cret-pw", "demo-token-abc123xyz", "demo-key-98765")
EXPECTED_SOURCES = ("git", "docker", "applog", "health")
TOP_N = 3                      # the real cause must be ranked at most this high


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseResult:
    name: str
    incident_type: str
    checks: tuple
    has_cause: bool = True
    start_err_s: float = None
    end_err_s: float = None
    cause_rank: int = None
    confidence: str = "-"

    @property
    def passed(self):
        return all(c.passed for c in self.checks)


def _matches(event, cause):
    return (event.type == cause["type"] and event.service == cause["service"]
            and cause["match"] in event.description)


def check_case(data_dir, cfg):
    """Run the whole analysis on one recorded incident and check it against ground_truth.json."""
    data_dir = Path(data_dir)
    gt = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    name = gt.get("name", data_dir.name)
    kind = gt.get("incident_type", "")
    tol = float(gt.get("tolerance_s", 5.0))
    cause = gt.get("cause")
    checks = []

    def add(label, ok, detail):
        checks.append(Check(label, bool(ok), detail))

    a = analyze(load_events(data_dir, cfg), cfg)
    report = generate_postmortem(a, cfg)

    have = {e.source for e in a.timeline}
    add("all sources in one timeline", set(EXPECTED_SOURCES) <= have,
        f"{len(a.timeline)} events from: {', '.join(sorted(have))}")
    add("timeline is time-ordered",
        all(x.ts <= y.ts for x, y in zip(a.timeline, a.timeline[1:])), "sorted by corrected time")

    inj = (gt.get("injected") or {}).get("git_clock_skew_s")
    if inj is not None:
        est = a.estimates.get("git")
        if est is None:
            add("injected git clock skew recovered", False, "no git events")
        else:
            ok = est.applied and abs(est.offset_s + float(inj)) <= tol
            add("injected git clock skew recovered", ok,
                f"injected +{float(inj):g}s, estimated {est.offset_s:+.1f}s, applied={est.applied}")

    inc = a.incident
    if inc is None:
        add("incident detected", False, "no incident found in the health probes")
        return CaseResult(name, kind, tuple(checks), has_cause=bool(cause))
    add("incident detected", True, f"service {inc.service}")

    start_err = (inc.start - parse_ts(gt["true_start"])).total_seconds()
    add("start within tolerance", abs(start_err) <= tol,
        f"error {start_err:+.1f}s (allowed +/-{tol:g}s)")
    end_err = None
    if inc.end is None:
        add("end within tolerance", False, "incident still ongoing at the end of the data")
    else:
        end_err = (inc.end - parse_ts(gt["true_end"])).total_seconds()
        add("end within tolerance", abs(end_err) <= tol,
            f"error {end_err:+.1f}s (allowed +/-{tol:g}s)")

    add("TTD and TTR are in the report",
        "Time to detect (TTD)" in report and "Time to recover (TTR)" in report, "Impact table")

    rank = None
    if cause:
        for s in a.ranking.suspects:
            if _matches(s.event, cause):
                rank = s.rank
                break
        add(f"real cause ranked in top {TOP_N}", rank is not None and rank <= TOP_N,
            f"'{cause['match']}' is " + (f"rank #{rank}" if rank else "not among the suspects"))
    else:
        expect = gt.get("expect_confidence", "low")
        add(f"confidence is {expect.upper()} (no clear cause)",
            a.confidence.level == expect, f"tool said {a.confidence.level.upper()}")
        add("report says there is no clear trigger", "No clear trigger" in report,
            "wording in 'Most likely trigger'")

    again = generate_postmortem(analyze(load_events(data_dir, cfg), cfg), cfg)
    shuffled = list(load_events(data_dir, cfg))
    random.Random(7).shuffle(shuffled)
    third = generate_postmortem(analyze(shuffled, cfg), cfg)
    add("same data gives the same report", report == again == third,
        "3 runs, one with shuffled input, byte-for-byte")

    texts = {"report": report}
    for p in sorted(data_dir.iterdir()):
        if p.is_file():
            texts[p.name] = p.read_text(encoding="utf-8", errors="ignore")
    leaks = [f"{src}:{s}" for src, txt in texts.items() for s in DEMO_SECRETS if s in txt]
    add("no demo secret in data or report", not leaks, "clean" if not leaks else ", ".join(leaks))

    return CaseResult(name, kind, tuple(checks), has_cause=bool(cause), start_err_s=start_err,
                      end_err_s=end_err, cause_rank=rank, confidence=a.confidence.level.upper())


# ---------- formatting ----------

def _err(v):
    return "n/a" if v is None else f"{v:+.1f}s"


def _rank(r):
    if not r.has_cause:
        return "none expected"
    return f"#{r.cause_rank}" if r.cause_rank else "not found"


def format_table(results):
    head = ("incident", "type", "start err", "end err", "cause rank", "confidence", "checks", "result")
    rows = [head]
    for r in results:
        ok = sum(c.passed for c in r.checks)
        rows.append((r.name, r.incident_type, _err(r.start_err_s), _err(r.end_err_s), _rank(r),
                     r.confidence, f"{ok}/{len(r.checks)}", "PASS" if r.passed else "FAIL"))
    widths = [max(len(row[i]) for row in rows) for i in range(len(head))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def format_details(results, verbose=False):
    lines = []
    for r in results:
        for c in r.checks:
            if verbose or not c.passed:
                lines.append(f"  {'ok  ' if c.passed else 'FAIL'} {r.name}: {c.name}: {c.detail}")
    return "\n".join(lines)


def format_markdown(results):
    done = sum(r.passed for r in results)
    out = ["# Ground-truth check", "",
           f"**{done} of {len(results)} recorded incidents passed.**", "",
           "| Incident | Type | Start error | End error | Cause rank | Confidence | Checks | Result |",
           "|---|---|---|---|---|---|---|---|"]
    for r in results:
        ok = sum(c.passed for c in r.checks)
        out.append(f"| {r.name} | {r.incident_type} | {_err(r.start_err_s)} | {_err(r.end_err_s)} "
                   f"| {_rank(r)} | {r.confidence} | {ok}/{len(r.checks)} "
                   f"| {'PASS' if r.passed else 'FAIL'} |")
    out += ["", "Start and end must be within the tolerance stored in each `ground_truth.json` "
                f"(5 s for the demo incidents). The real cause must be in the top {TOP_N}; "
                "the no-cause incident must give a LOW-confidence report that says so.", ""]
    return "\n".join(out)

#!/usr/bin/env python3
"""Demo environment and scenario runner (Docker Compose project "itb").

    python demo/scenario.py up              build image, start web + db, wait until healthy
    python demo/scenario.py status          show itb-* containers and web health
    python demo/scenario.py run NAME|all    record a scenario into data/incidents/NAME/
    python demo/scenario.py down            stop and remove itb-* containers and the network
    python demo/scenario.py clean           down + remove the itb-demo image and demo/run

Only things named itb-* (compose project "itb") are touched. Ports: 18080 web, 18081 db.
Every recorded line is redacted before it is written.
"""
import argparse
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from itb.record import dump_jsonl_line, git_record, iso, redact_log_text
from itb.redact import redact

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
COMPOSE = DEMO / "compose.yaml"
RUN_LOGS = DEMO / "run" / "logs"
OUT_ROOT = ROOT / "data" / "incidents"
PROJECT = "itb"
IMAGE = "itb-demo:latest"
BASE_URL = "http://127.0.0.1:18080"
GIT_SKEW_S = 60.0          # the git/deploy clock runs 60s ahead, on purpose
APP_TZ = "+05:30"          # the app logs naive IST time, on purpose
PROBE_INTERVAL_S = 1.0
TOLERANCE_S = 5.0


# ---------- docker / http helpers ----------

def sh(cmd, env=None, check=True, capture=False):
    return subprocess.run(cmd, env=env, check=check, text=True, capture_output=capture)


def compose(*args, env=None, check=True):
    return sh(["docker", "compose", "-f", str(COMPOSE), "-p", PROJECT, *args],
              env=env, check=check)


def http_status(path, timeout=0.8):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def wait_healthy(timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        if http_status("/health") == 200:
            return time.time()
        time.sleep(0.2)
    raise RuntimeError("web did not become healthy in time")


def build_image():
    sh(["docker", "build", "-q", "-t", IMAGE, str(DEMO)])


def parse_docker_time(text):
    base, _, frac = text.rstrip("Z").partition(".")
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.timestamp() + (float("0." + frac) if frac else 0.0)


# ---------- recorder ----------

class Recorder:
    def __init__(self, out):
        self.stop_evt = threading.Event()
        self.lock = threading.Lock()
        self.threads = []
        self.proc = None
        self.files = {key: open(out / name, "w", encoding="utf-8")
                      for key, name in (("docker", "docker.jsonl"),
                                        ("health", "health.jsonl"),
                                        ("git", "git.jsonl"))}

    def _write(self, key, line):
        with self.lock:
            self.files[key].write(line + "\n")
            self.files[key].flush()

    def git(self, rec):
        self._write("git", dump_jsonl_line(rec))

    def start_docker_events(self):
        cmd = ["docker", "events", "--format", "{{json .}}", "--filter", "type=container",
               "--filter", f"label=com.docker.compose.project={PROJECT}"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        t = threading.Thread(target=self._read_events, daemon=True)
        t.start()
        self.threads.append(t)
        time.sleep(1.0)

    def _read_events(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            self._write("docker", dump_jsonl_line(obj))

    def start_prober(self):
        t = threading.Thread(target=self._probe_loop, daemon=True)
        t.start()
        self.threads.append(t)

    def _probe_loop(self):
        nxt = time.time()
        while not self.stop_evt.is_set():
            started = time.time()
            status = http_status("/health", timeout=0.8)
            rec = {"ts": iso(started), "service": "web", "ok": status == 200,
                   "status": status, "latency_ms": int((time.time() - started) * 1000)}
            self._write("health", dump_jsonl_line(rec))
            nxt += PROBE_INTERVAL_S
            delay = nxt - time.time()
            if delay > 0:
                self.stop_evt.wait(delay)
            else:
                nxt = time.time()

    def stop(self):
        self.stop_evt.set()
        if self.proc:
            self.proc.terminate()
        for t in self.threads:
            t.join(timeout=3)
        for f in self.files.values():
            f.close()


# ---------- scenario context ----------

class Ctx:
    def __init__(self, name, out):
        self.name, self.out = name, out
        self.rec = Recorder(out)
        self.t0 = None

    def say(self, msg):
        stamp = f"[{time.time() - self.t0:6.1f}s]" if self.t0 else "[ setup  ]"
        print(f"{stamp} {redact(msg)}", flush=True)

    def sleep_until(self, offset):
        delay = self.t0 + offset - time.time()
        if delay > 0:
            time.sleep(delay)

    def deploy(self, version, bug, message, files, first=False):
        """Write the deploy record (git clock is skewed), then (re)create web."""
        ts = time.time()
        self.rec.git(git_record(ts, message, "web", files, skew_s=GIT_SKEW_S))
        env = {**__import__("os").environ, "ITB_WEB_VERSION": version, "ITB_WEB_BUG": bug}
        if first:
            compose("up", "-d", env=env)
        else:
            compose("up", "-d", "--no-deps", "--force-recreate", "web", env=env)
        self.say(f"deploy {version}{' bug=' + bug if bug else ''}: {message}")
        return ts

    def wait_oom(self, timeout=90.0):
        end = time.time() + timeout
        while time.time() < end:
            r = sh(["docker", "inspect", "-f",
                    "{{.State.Status}}|{{.State.OOMKilled}}|{{.State.FinishedAt}}",
                    "itb-web"], check=False, capture=True)
            parts = r.stdout.strip().split("|")
            if len(parts) == 3 and parts[0] == "exited" and parts[1] == "true":
                return parse_docker_time(parts[2])
            time.sleep(0.5)
        raise RuntimeError("web was not OOM-killed in time")

    def tail(self, t_ok, secs=20):
        self.sleep_until(t_ok - self.t0 + secs)


# ---------- scenarios (offsets are seconds after recording start) ----------

def sc_bad_deploy(c):
    c.sleep_until(30)
    c.deploy("v1.1", "", "bump http client timeout, token=demo-token-abc123xyz",
             ["app/http_client.py"])
    c.sleep_until(100)
    t_fault = c.deploy("v2", "bad_driver", "switch to new db driver",
                       ["app/db_client.py", "requirements.txt"])
    c.say("FAULT: v2 is live and its health check fails")
    c.sleep_until(170)
    c.deploy("v1.1", "", "rollback: revert new db driver", ["app/db_client.py"])
    t_ok = wait_healthy()
    c.say("RECOVERED: rollback is healthy")
    c.tail(t_ok)
    return {"cause": {"type": "deploy", "service": "web", "match": "switch to new db driver"},
            "true_start": t_fault, "true_end": t_ok}


def sc_failing_dependency(c):
    c.sleep_until(30)
    c.deploy("v1.1", "", "tune log format", ["app/logging.py"])
    c.sleep_until(100)
    t_fault = time.time()
    sh(["docker", "kill", "itb-db"])
    c.say("FAULT: database container killed")
    c.sleep_until(170)
    sh(["docker", "start", "itb-db"])
    t_ok = wait_healthy()
    c.say("RECOVERED: database is back")
    c.tail(t_ok)
    return {"cause": {"type": "restart", "service": "db", "match": "itb-db"},
            "true_start": t_fault, "true_end": t_ok}


def sc_resource_exhaustion(c):
    c.sleep_until(30)
    c.deploy("v1.1", "", "tune thread pool size", ["app/pool.py"])
    c.sleep_until(100)
    c.deploy("v2", "leak", "add in-memory image cache", ["app/cache.py"])
    c.say("FAULT: v2 leaks memory, waiting for the OOM kill ...")
    t_fault = c.wait_oom()
    c.say("web was OOM-killed")
    c.sleep_until(170)
    c.deploy("v1.1", "", "rollback: remove in-memory image cache", ["app/cache.py"])
    t_ok = wait_healthy()
    c.say("RECOVERED: rollback is healthy")
    c.tail(t_ok)
    return {"cause": {"type": "deploy", "service": "web", "match": "in-memory image cache"},
            "true_start": t_fault, "true_end": t_ok}


def sc_no_clear_cause(c):
    c.sleep_until(15)
    c.deploy("v1.1", "", "tune log format", ["app/logging.py"])
    c.sleep_until(180)
    t_fault = time.time()
    http_status("/admin/fault?mode=errors")
    c.say("FAULT: upstream problem injected (no change event exists for it)")
    c.sleep_until(250)
    http_status("/admin/fault?mode=none")
    t_ok = wait_healthy()
    c.say("RECOVERED: upstream problem gone")
    c.tail(t_ok)
    return {"cause": None, "expect_confidence": "low",
            "true_start": t_fault, "true_end": t_ok}


SCENARIOS = {
    "bad_deploy": {"run": sc_bad_deploy, "type": "bad deploy",
                   "description": "A new version switches the db driver and its health check fails; rollback fixes it."},
    "failing_dependency": {"run": sc_failing_dependency, "type": "failing dependency",
                           "description": "The database container is killed; web health fails until it is started again."},
    "resource_exhaustion": {"run": sc_resource_exhaustion, "type": "resource exhaustion",
                            "description": "A new version leaks memory and web is OOM-killed; rollback fixes it."},
    "no_clear_cause": {"run": sc_no_clear_cause, "type": "no clear cause",
                       "description": "An upstream problem breaks web with no change recorded; only old harmless deploys exist."},
}


# ---------- commands ----------

def finish(out, name, spec, truth):
    src = RUN_LOGS / "app.log"
    text = src.read_text(encoding="utf-8", errors="replace") if src.exists() else ""
    (out / "app.log").write_text(redact_log_text(text), encoding="utf-8")
    meta = {"name": name, "description": spec["description"],
            "source_tz": {"applog": APP_TZ}, "probe_interval_s": PROBE_INTERVAL_S,
            "recorded_with": "demo/scenario.py"}
    gt = {"name": name, "incident_type": spec["type"], "description": spec["description"],
          "tolerance_s": TOLERANCE_S, "cause": truth["cause"],
          "true_start": iso(truth["true_start"]), "true_end": iso(truth["true_end"]),
          "injected": {"git_clock_skew_s": GIT_SKEW_S, "applog_timezone": APP_TZ,
                       "probe_interval_s": PROBE_INTERVAL_S}}
    if "expect_confidence" in truth:
        gt["expect_confidence"] = truth["expect_confidence"]
    for fname, obj in (("meta.json", meta), ("ground_truth.json", gt)):
        (out / fname).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")


def run_scenario(name):
    spec = SCENARIOS[name]
    out = OUT_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for f in out.iterdir():
        if f.is_file():
            f.unlink()
    RUN_LOGS.mkdir(parents=True, exist_ok=True)
    build_image()
    compose("down", "-v", "--remove-orphans", check=False)
    log_file = RUN_LOGS / "app.log"
    if log_file.exists():
        log_file.unlink()

    c = Ctx(name, out)
    truth = None
    try:
        c.rec.start_docker_events()
        c.deploy("v1", "", "initial release v1", ["app/web.py"], first=True)
        wait_healthy()
        c.rec.start_prober()
        c.t0 = time.time()
        c.say(f"recording scenario '{name}' (about 3-5 minutes)")
        truth = spec["run"](c)
    finally:
        c.rec.stop()
        compose("down", "-v", "--remove-orphans", check=False)
    finish(out, name, spec, truth)
    print(f"done: {out}")


def cmd_up():
    RUN_LOGS.mkdir(parents=True, exist_ok=True)
    build_image()
    compose("up", "-d")
    wait_healthy()
    print("web: http://127.0.0.1:18080/health  db: 127.0.0.1:18081")


def cmd_status():
    sh(["docker", "ps", "-a", "--filter", "name=itb-",
        "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"])
    print("web /health ->", http_status("/health"))


def cmd_down():
    compose("down", "-v", "--remove-orphans", check=False)


def cmd_clean():
    cmd_down()
    sh(["docker", "rmi", IMAGE], check=False)
    shutil.rmtree(DEMO / "run", ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("up", "status", "down", "clean"):
        sub.add_parser(n)
    r = sub.add_parser("run")
    r.add_argument("name", choices=[*SCENARIOS, "all"])
    args = ap.parse_args()
    if args.cmd == "run":
        for n in (SCENARIOS if args.name == "all" else [args.name]):
            run_scenario(n)
    else:
        {"up": cmd_up, "status": cmd_status, "down": cmd_down, "clean": cmd_clean}[args.cmd]()


if __name__ == "__main__":
    main()

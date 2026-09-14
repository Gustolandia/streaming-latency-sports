#!/usr/bin/env python3
"""
run_queue.py -- the randomised run queue, and the ledger it keeps of every run.

The rules, in the order they act:

  rounds       every setup appears once per round;
  shuffle      within each round, from one generator whose seed is written into every row;
  no repeats   a round may not open with the setup the previous round closed on;
  failures     a run that fails mechanically keeps its row, marked failed with its reason, and a
               copy goes back into the queue at a random later place, never beside a run of the
               same setup if that can be avoided. After MAX_ATTEMPTS the last copy is marked
               abandoned: a status, not a deletion;
  surprises    a run that completes is done, whatever number it produced. Nothing here puts a
               finished run back in the queue, because a campaign that re-runs the runs it did
               not like is a selection of runs, not a sweep.

Settings that need a reboot or a fresh machine (the tick, the kernel, the core count, the
cloud) cannot change run by run. They are sessions. `sessions` orders them under the same two
rules, and each session gets its own queue.

The queue is a CSV, so a person can read it and a crash leaves it readable; every write goes
through a temporary file. A runner that dies mid-run leaves a row marked running, and `next`
refuses to hand out another run until `--recover` has recorded that one as a failure.

A design is JSON: {"seed": 20260914, "rounds": 20, "setups": [{"id": "s1500_d2.0",
"slice_ns": 1500000, "delay_ms": 2.0}, ...]}. Everything except "id" is passed through to the
runner as the run's parameters.

CLI:
    python3 scripts/run_queue.py make --design design.json --out queue.csv
    python3 scripts/run_queue.py next --queue queue.csv [--recover]
    python3 scripts/run_queue.py finish --queue queue.csv --key K --status done --run-dir runs/x
    python3 scripts/run_queue.py finish --queue queue.csv --key K --status failed --reason "..."
    python3 scripts/run_queue.py report --queue queue.csv
    python3 scripts/run_queue.py sessions --types hz1000,hz250 --repeats 2 --seed 7
"""
import argparse
import csv
import datetime
import json
import os
import random
import sys

FIELDS = ("key", "round", "setup", "params", "status", "attempt", "reason",
          "started_utc", "finished_utc", "run_dir", "seed")
STATUSES = ("queued", "running", "done", "failed", "abandoned")
MAX_ATTEMPTS = 3

#: Times of day, in UTC, that the report balances runs across.
BUCKETS = ((0, "night"), (6, "morning"), (12, "afternoon"), (18, "evening"))


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shuffled_rounds(items, rounds, rng):
    """`rounds` shuffles of `items`, each reshuffled until it does not open with the item the
    previous one closed on. Callers make sure there are two distinct items when rounds > 1."""
    out, last = [], None
    for _ in range(rounds):
        order = list(items)
        rng.shuffle(order)
        while order[0] == last:
            rng.shuffle(order)
        out.append(order)
        last = order[-1]
    return out


def _whole(value, least):
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def check_design(design):
    """Why the design cannot become a queue, as sentences; empty if it can."""
    setups = design.get("setups")
    if not isinstance(setups, list) or not setups:
        return ["the design has no setups"]
    out = []
    ids = [s.get("id") for s in setups]
    if not all(isinstance(i, str) and i for i in ids):
        out.append("every setup needs a non-empty string id")
    repeated = sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})
    if repeated:
        out.append("setup ids repeat: %s" % ", ".join(repeated))
    if not _whole(design.get("rounds"), 1):
        out.append("rounds must be a whole number of at least 1")
    elif design["rounds"] > 1 and len(setups) < 2:
        out.append("with a single setup, consecutive rounds cannot avoid repeating it")
    if not _whole(design.get("seed"), 0):
        out.append("seed must be a whole number, written down before the queue is made")
    return out


def make_rows(design):
    problems = check_design(design)
    if problems:
        raise ValueError("; ".join(problems))
    by_id = {s["id"]: s for s in design["setups"]}
    rng = random.Random(design["seed"])
    rows = []
    for r, order in enumerate(shuffled_rounds(list(by_id), design["rounds"], rng), 1):
        for setup in order:
            params = {k: v for k, v in by_id[setup].items() if k != "id"}
            rows.append({"key": "r%03d-%s-a1" % (r, setup), "round": str(r), "setup": setup,
                         "params": json.dumps(params, sort_keys=True), "status": "queued",
                         "attempt": "1", "reason": "", "started_utc": "", "finished_utc": "",
                         "run_dir": "", "seed": str(design["seed"])})
    return rows


def read_queue(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row.get("status") not in STATUSES:
            raise ValueError("%s: run %s has status %r" % (path, row.get("key"), row.get("status")))
    return rows


def write_queue(path, rows):
    """Write through a temporary file, so a crash mid-write leaves the old queue, not half one."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def index(rows, key):
    for i, row in enumerate(rows):
        if row["key"] == key:
            return i
    raise KeyError("no run %r in the queue" % key)


def _beside_same_setup(rows, position, setup):
    """True if inserting `setup` at `position` would put it next to a run of the same setup."""
    before = rows[position - 1]["setup"] if position > 0 else None
    after = rows[position]["setup"] if position < len(rows) else None
    return setup in (before, after)


def fail(rows, key, reason, clock=now_utc, run_dir=""):
    """Record a mechanical failure and put a copy later in the queue.

    Returns the copy, or None when the attempts are used up and the run is abandoned instead.
    """
    i = index(rows, key)
    row = rows[i]
    row.update(status="failed", reason=reason, finished_utc=clock(), run_dir=run_dir)
    attempt = int(row["attempt"])
    if attempt >= MAX_ATTEMPTS:
        row["status"] = "abandoned"
        return None
    copy = dict(row, status="queued", attempt=str(attempt + 1), reason="", started_utc="",
                finished_utc="", run_dir="",
                key="%s-a%d" % (row["key"].rsplit("-a", 1)[0], attempt + 1))
    rng = random.Random("%s:%s" % (row["seed"], copy["key"]))
    later = list(range(i + 1, len(rows) + 1))
    allowed = [p for p in later if not _beside_same_setup(rows, p, row["setup"])]
    rows.insert(rng.choice(allowed or later), copy)
    return copy


def take_next(rows, recover=False, clock=now_utc):
    """Mark the first queued run running and return it, or None when nothing is left.

    A run already marked running means the last runner stopped without reporting. Handing out
    another run then would leave that one unrecorded, so it is refused unless `recover` records
    it as a failure first.
    """
    running = [r["key"] for r in rows if r["status"] == "running"]
    if running and not recover:
        raise RuntimeError("%s is still marked running; if its runner is gone, use --recover"
                           % running[0])
    for key in running:
        fail(rows, key, "the runner stopped while this run was in progress", clock)
    for row in rows:
        if row["status"] == "queued":
            row.update(status="running", started_utc=clock())
            return row
    return None


def finish(rows, key, status, reason="", run_dir="", clock=now_utc):
    """Close a running run as done or failed. Returns the re-queued copy of a failed run."""
    row = rows[index(rows, key)]
    if row["status"] != "running":
        raise RuntimeError("%s is %s, not running; only a running run can finish"
                           % (key, row["status"]))
    if status == "done":
        row.update(status="done", reason=reason, finished_utc=clock(), run_dir=run_dir)
        return None
    if status != "failed":
        raise ValueError("a run finishes as done or failed, not %r" % status)
    if not reason:
        raise ValueError("a failed run needs its reason; the ledger keeps why, not only that")
    return fail(rows, key, reason, clock, run_dir)


def bucket(stamp):
    hour = int(stamp[11:13])
    return [label for start, label in BUCKETS if hour >= start][-1]


def report(rows):
    """Status counts, completed runs per setup by time of day, and every failure with its reason."""
    lines = ["runs: " + ", ".join("%s %d" % (s, sum(1 for r in rows if r["status"] == s))
                                  for s in STATUSES),
             "done per setup, by time of day (UTC):"]
    for setup in sorted({r["setup"] for r in rows}):
        done = [r for r in rows if r["setup"] == setup and r["status"] == "done"]
        per = {label: 0 for _, label in BUCKETS}
        for r in done:
            per[bucket(r["started_utc"])] += 1
        lines.append("  %-24s %4d   %s" % (setup, len(done), "  ".join(
            "%s %d" % (label, per[label]) for _, label in BUCKETS)))
    failures = [r for r in rows if r["status"] in ("failed", "abandoned")]
    if failures:
        lines.append("failures:")
        lines += ["  %s %s: %s" % (r["key"], r["status"], r["reason"]) for r in failures]
    return lines


def session_order(types, repeats, seed):
    """Session types, each `repeats` times, in shuffled rounds that never repeat back to back."""
    if not types:
        raise ValueError("no session types")
    if len(set(types)) != len(types):
        raise ValueError("session types repeat: %s" % ", ".join(types))
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if repeats > 1 and len(types) < 2:
        raise ValueError("a single session type repeated cannot avoid following itself")
    rounds = shuffled_rounds(types, repeats, random.Random(seed))
    return [t for order in rounds for t in order]


def main(argv=None, out=None, clock=now_utc):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="The randomised run queue and its ledger")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("make")
    p.add_argument("--design", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("next")
    p.add_argument("--queue", required=True)
    p.add_argument("--recover", action="store_true")
    p = sub.add_parser("finish")
    p.add_argument("--queue", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--status", choices=("done", "failed"), required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--run-dir", default="")
    p = sub.add_parser("report")
    p.add_argument("--queue", required=True)
    p = sub.add_parser("sessions")
    p.add_argument("--types", required=True)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--seed", type=int, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "make":
            if os.path.exists(args.out):
                started = [r["key"] for r in read_queue(args.out) if r["status"] != "queued"]
                if started or not args.force:
                    raise RuntimeError(
                        "%s exists%s. A queue is a ledger, so it is never remade over runs it "
                        "recorded; --force replaces only a queue that has not started"
                        % (args.out, " and has started (%s)" % started[0] if started else ""))
            with open(args.design, encoding="utf-8") as fh:
                design = json.load(fh)
            rows = make_rows(design)
            write_queue(args.out, rows)
            print("%d runs in %d rounds, seed %d -> %s"
                  % (len(rows), design["rounds"], design["seed"], args.out), file=out)
            return 0
        if args.command == "sessions":
            types = [t.strip() for t in args.types.split(",") if t.strip()]
            for n, kind in enumerate(session_order(types, args.repeats, args.seed), 1):
                print("%d. %s" % (n, kind), file=out)
            return 0
        rows = read_queue(args.queue)
        if args.command == "report":
            for line in report(rows):
                print(line, file=out)
            return 0
        if args.command == "next":
            row = take_next(rows, args.recover, clock)
            write_queue(args.queue, rows)
            if row is None:
                print("the queue is finished", file=out)
                return 3
            print(json.dumps({"key": row["key"], "setup": row["setup"], "round": row["round"],
                              "attempt": row["attempt"], "params": json.loads(row["params"])},
                             sort_keys=True), file=out)
            return 0
        copy = finish(rows, args.key, args.status, args.reason, args.run_dir, clock)
        write_queue(args.queue, rows)
        if args.status == "done":
            print("%s done" % args.key, file=out)
        elif copy is None:
            print("%s failed for the last time and is abandoned" % args.key, file=out)
        else:
            print("%s failed; queued again as %s" % (args.key, copy["key"]), file=out)
        return 0
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

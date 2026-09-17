#!/usr/bin/env python3
"""
pilot_checks.py -- the checks a machine must pass before its runs count, read from run files.

They are about the instrument, not the result:

  never negative   arrival minus sending can never be below zero. Both timestamps are read from
                   one clock on one machine, and a message cannot arrive before it was sent. A
                   negative one means the harness is broken, and nothing else in that run can be
                   trusted.
  receiver only    with the receiver-only delay added, the producer's "got it" delay stays where
                   it was (median within 0.05 ms) and arrival minus sending grows by the added
                   amount (within 0.05 ms). Otherwise the delay reached the wrong path, which is
                   how the earlier broker-side delay produced a null.
  go-first         real-time priority on the timestamping processes cuts the negative rate at
                   least FACTOR-fold at every load level, with the manipulation check passed.
                   On Oracle it did; a machine that cannot reproduce it cleanly is not yet the
                   machine to test a law on.
  paths            with no delay, how far the receiver's round trip to the broker sits from the
                   host's, measured three ways: by TCP and UDP (sockperf, the tool Microsoft's own
                   guidance names) and by ping. Recorded, not required (plan v7): on 17 September
                   ping put the two paths 0.283 ms apart, steadily, where TCP put them 0.009 ms
                   apart, and a gate on ping's figure had already turned a sound pair away. What
                   a pair's runs actually vary by is measured by B0 and sets its rounds.
  shakedown        what a machine pair must pass, read from one pilot's output, before its first
                   campaign: the settings, the receiver-only delay (held by the broker for the
                   receiver alone, and seen by ping end to end) and the paths (the pilot's own
                   verdicts), no negative trip in the harness runs, and the load within
                   LOAD_POINTS of its setting in every harness cell. A later session of the same
                   pair asks for the network checks alone (--checks network,paths). The pilot's
                   harness verdict also asks that the trip grow one-for-one with the delay; it
                   replays the football match in bursts, and in bursts the trip does not, so each
                   session's calibration, on the campaign's steady traffic, judges that instead.
                   Go-first is reported but not required, because the campaign tests it as a
                   prediction.

Per message, from producer.csv and consumer_events.csv joined on event_id (the files and join
analyze_depth.run_inversion uses):

    trip      t_consume_ns - t_prod_send_ns       arrival minus sending
    got it    t_broker_ack_ns - t_prod_send_ns    how late the acknowledgement was written
    measured  t_consume_ns - t_broker_ack_ns      the span a benchmark reports, negative when
                                                  the "got it" note is written late

Messages sent in the first `--warmup-s` seconds of a run are left out.

CLI:
    python3 scripts/pilot_checks.py run runs/<run_id> [--warmup-s 30]
    python3 scripts/pilot_checks.py list --out-dir <campaign cell dir> [--backend kafka]
    python3 scripts/pilot_checks.py compare --baseline runs/a runs/b --step runs/c --added-ms 2.0
    python3 scripts/pilot_checks.py go-first --table <dir>/stamping_priority.csv [--factor 5]
    python3 scripts/pilot_checks.py paths --pilot-dir <pilot output dir>
    python3 scripts/pilot_checks.py shakedown --pilot-dir <pilot output dir> [--load-pct 75] \
        [--checks network,paths]
"""
import argparse
import csv
import glob
import json
import os
import statistics
import sys

TOLERANCE_MS = 0.05
FACTOR = 5.0
#: A harness cell's mean load may differ from its setting by this many percentage points.
LOAD_POINTS = 3.0
#: The pilot writes one receiver-only report per backend.
HARNESS_REPORTS = ("harness_verify_kafka.json", "harness_verify_redis.json")
#: With no delay, the receiver's and the host's round trips may differ by this much: the limit
#: every run's added delay is held to (plan v6).
PATHS_MS = 0.25
#: Every check a shakedown can be asked for.
ALL_CHECKS = ("settings", "network", "paths", "never_negative", "load")
#: What a shakedown asks for, unless it is told otherwise. The paths are recorded, not required.
SHAKEDOWN_CHECKS = ("settings", "network", "never_negative", "load")


def _int(value):
    return int(value) if value not in (None, "", "None") else None


def spans(run_dir, warmup_s=30.0):
    """(trip, got it, measured) lists in ms for one run, after the warm-up."""
    sent = {}
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sent[r["event_id"]] = (_int(r.get("t_prod_send_ns")), _int(r.get("t_broker_ack_ns")))
    starts = [s for s, _ in sent.values() if s is not None]
    if not starts:
        raise ValueError("%s: the producer recorded no send times" % run_dir)
    cutoff = min(starts) + int(warmup_s * 1e9)
    trip, gotit, measured = [], [], []
    with open(os.path.join(run_dir, "consumer_events.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            send, ack = sent.get(r["event_id"], (None, None))
            received = _int(r.get("t_consume_ns"))
            if send is None or received is None or send < cutoff:
                continue
            trip.append((received - send) / 1e6)
            if ack is not None:
                gotit.append((ack - send) / 1e6)
                measured.append((received - ack) / 1e6)
    return trip, gotit, measured


def summarise(run_dir, warmup_s=30.0):
    trip, gotit, measured = spans(run_dir, warmup_s)
    if not trip:
        raise ValueError("%s: no message sent after the first %g s arrived" % (run_dir, warmup_s))
    negative = sum(1 for s in measured if s < 0)
    return {
        "run_dir": run_dir,
        "warmup_s": warmup_s,
        "messages": len(trip),
        "trip_negative": sum(1 for d in trip if d < 0),
        "trip_median_ms": statistics.median(trip),
        "gotit_median_ms": statistics.median(gotit) if gotit else None,
        # The tail the session calibration's "got it" check also watches (delay_calibration.py):
        # a helper kept waiting for a core shows first in the slowest acknowledgements.
        "gotit_p99_ms": (statistics.quantiles(gotit, n=100, method="inclusive")[98]
                         if len(gotit) > 1 else (gotit[0] if gotit else None)),
        "measured_negative": negative,
        "measured_spans": len(measured),
        "measured_negative_rate": negative / len(measured) if measured else None,
    }


def _median_of_runs(runs, key):
    """The median over runs of each run's median: runs differ in length, and pooling messages
    would let a long run outvote a short one."""
    values = [r[key] for r in runs if r[key] is not None]
    if not values:
        raise ValueError("no %s in %s" % (key, ", ".join(r["run_dir"] for r in runs)))
    return statistics.median(values)


def compare(baseline, step, added_ms, tolerance_ms=TOLERANCE_MS):
    """The receiver-only check, on run summaries without and with the delay."""
    gotit_shift = _median_of_runs(step, "gotit_median_ms") - _median_of_runs(
        baseline, "gotit_median_ms")
    trip_shift = _median_of_runs(step, "trip_median_ms") - _median_of_runs(
        baseline, "trip_median_ms")
    negatives = sum(r["trip_negative"] for r in baseline + step)
    report = {
        "added_ms": added_ms,
        "tolerance_ms": tolerance_ms,
        "gotit_shift_ms": gotit_shift,
        "trip_shift_ms": trip_shift,
        "trip_negative_total": negatives,
        "gotit_unchanged": abs(gotit_shift) <= tolerance_ms,
        "trip_moved_by_the_delay": abs(trip_shift - added_ms) <= tolerance_ms,
        "never_negative": negatives == 0,
        "baseline_runs": [r["run_dir"] for r in baseline],
        "step_runs": [r["run_dir"] for r in step],
    }
    report["ok"] = (report["gotit_unchanged"] and report["trip_moved_by_the_delay"]
                    and report["never_negative"])
    return report


def runs_in(out_dir, backend=None):
    """Run directories a run_concurrency_test.py invocation wrote, from its own run list."""
    found = []
    for summary in sorted(glob.glob(os.path.join(out_dir, "concurrency_*", "*_summary.json"))):
        with open(summary, encoding="utf-8") as fh:
            listing = json.load(fh)["run_list_file"]
        with open(listing, encoding="utf-8") as fh:
            for line in fh:
                run = line.strip()
                if run and (backend is None or "_%s_" % backend in os.path.basename(run)):
                    found.append(run)
    return found


def go_first(table, factor=FACTOR):
    """Did real-time priority cut the negative rate at least `factor`-fold at every level?

    Reads analyze_stamping_priority.py's table. A level that failed its manipulation check
    fails here too rather than being skipped: the question is whether this machine reproduces
    the effect cleanly, and a confounded level is not a clean answer.
    """
    with open(table, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError("%s has no load levels" % table)
    levels = []
    for r in rows:
        ratio = float(r["ratio"]) if r["ratio"] not in ("", "None") else None
        if r["confounded"] == "True":
            ok, why = False, "the manipulation check failed"
        elif ratio is None:
            ok, why = False, "the ordinary arm had no negatives, so there was nothing to cut"
        else:
            ok = ratio <= 1.0 / factor and r["disjoint"] == "True"
            why = "ratio %.4f against at most %.4f, intervals %s" % (
                ratio, 1.0 / factor, "disjoint" if r["disjoint"] == "True" else "overlapping")
        levels.append({"level": r["level"], "ok": ok, "why": why})
    return {"factor": factor, "ok": all(level["ok"] for level in levels), "levels": levels}


def _verdict_check(verdicts, name):
    """One of the pilot's own checks: passed only if it wrote rows and every row says yes."""
    rows = [r for r in verdicts if r.get("check") == name]
    detail = "; ".join("%s %s (%s)" % (r.get("step"), r.get("ok"), r.get("detail")) for r in rows)
    return {"ok": bool(rows) and all(r.get("ok") == "yes" for r in rows),
            "detail": detail or "the pilot wrote no %s verdict" % name}


def _cell_load(path):
    """A harness cell's mean load in per cent, or None when it holds no readable sample."""
    samples = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                samples.append(100.0 * float(row["rho"]))
            except (KeyError, TypeError, ValueError):
                continue
    return statistics.mean(samples) if samples else None


def sockperf_ms(path):
    """The median round trip sockperf measured, in ms, or None when there is nothing to read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "percentile 50.000" in line:
                    return float(line.rsplit("=", 1)[1]) / 1000.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def paths(pilot_dir, limit_ms=PATHS_MS):
    """How far the receiver's round trip to the broker sits from the host's with no delay, by
    ping (the median over the pilot's zero-delay readings) and, where the pilot measured them, by
    TCP and UDP. Recorded, not required: TCP is the one our messages use, so it decides `ok`
    where it exists."""
    files = sorted(glob.glob(os.path.join(pilot_dir, "net_zero*.json")))
    differences = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            reading = json.load(fh)
        differences.append(reading["receiver_median_ms"] - reading["host_median_ms"])
    if not differences:
        raise ValueError("%s holds no zero-delay reading (net_zero*.json)" % pilot_dir)
    middle = statistics.median(differences)
    readings = {}
    for name in ("tcp_host", "tcp_receiver", "udp_host", "udp_receiver"):
        value = sockperf_ms(os.path.join(pilot_dir, "sockperf_%s.txt" % name))
        if value is not None:
            readings[name] = value
    found = {"ping_difference_ms": middle, "median_difference_ms": middle,
             "differences_ms": differences, "limit_ms": limit_ms,
             "files": [os.path.basename(p) for p in files], "sockperf_ms": readings}
    for kind in ("tcp", "udp"):
        pair = ("%s_host" % kind, "%s_receiver" % kind)
        if all(name in readings for name in pair):
            found["%s_difference_ms" % kind] = readings[pair[1]] - readings[pair[0]]
    decides = found.get("tcp_difference_ms", middle)
    found["ok"] = abs(decides) <= limit_ms
    return found


def shakedown(pilot_dir, load_pct, load_points=LOAD_POINTS, wanted=SHAKEDOWN_CHECKS):
    """The instrument checks a machine pair must pass, read from one pilot's output."""
    unknown = sorted(set(wanted) - set(ALL_CHECKS))
    if unknown or not wanted:
        raise ValueError("a shakedown asks for some of %s, not %s"
                         % (", ".join(ALL_CHECKS), ", ".join(unknown) or "none"))
    with open(os.path.join(pilot_dir, "verdicts.csv"), newline="", encoding="utf-8") as fh:
        verdicts = list(csv.DictReader(fh))
    checks = {name: _verdict_check(verdicts, name) for name in ("settings", "network", "paths")}
    negatives, unreadable = 0, []
    for name in HARNESS_REPORTS:
        try:
            with open(os.path.join(pilot_dir, name), encoding="utf-8") as fh:
                negatives += int(json.load(fh)["trip_negative_total"])
        except (OSError, ValueError, KeyError, TypeError):
            unreadable.append(name)
    checks["never_negative"] = {
        "ok": negatives == 0 and not unreadable,
        "detail": "%d negative trip(s)%s" % (
            negatives, "; unreadable: " + ", ".join(unreadable) if unreadable else "")}
    loads = {os.path.basename(os.path.dirname(path)): _cell_load(path)
             for path in sorted(glob.glob(os.path.join(pilot_dir, "harness_*", "utilisation.csv")))}
    off = [cell for cell, load in loads.items()
           if load is None or abs(load - load_pct) > load_points]
    checks["load"] = {
        "ok": bool(loads) and not off,
        "detail": ", ".join("%s %s" % (cell, "no samples" if load is None else "%.1f%%" % load)
                            for cell, load in sorted(loads.items()))
        or "no harness cell recorded its load"}
    checks = {name: checks[name] for name in wanted}
    return {"pilot_dir": pilot_dir, "load_pct": load_pct, "load_points": load_points,
            "checks": checks, "ok": all(check["ok"] for check in checks.values()),
            "go_first_recorded": _verdict_check(verdicts, "go-first")["detail"]}


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Instrument checks a run must pass before it counts")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("run_dir")
    p.add_argument("--warmup-s", type=float, default=30.0)
    p = sub.add_parser("list")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--backend", choices=("kafka", "redis"))
    p = sub.add_parser("compare")
    p.add_argument("--baseline", nargs="+", required=True)
    p.add_argument("--step", nargs="+", required=True)
    p.add_argument("--added-ms", type=float, required=True)
    p.add_argument("--tolerance-ms", type=float, default=TOLERANCE_MS)
    p.add_argument("--warmup-s", type=float, default=30.0)
    p = sub.add_parser("go-first")
    p.add_argument("--table", required=True)
    p.add_argument("--factor", type=float, default=FACTOR)
    p = sub.add_parser("shakedown")
    p.add_argument("--pilot-dir", required=True)
    p.add_argument("--load-pct", type=float, default=75.0)
    p.add_argument("--load-points", type=float, default=LOAD_POINTS)
    p.add_argument("--checks", default=",".join(SHAKEDOWN_CHECKS),
                   help="the checks to require, comma-separated")
    p = sub.add_parser("paths")
    p.add_argument("--pilot-dir", required=True)
    p.add_argument("--limit-ms", type=float, default=PATHS_MS)
    args = ap.parse_args(argv)
    try:
        if args.command == "list":
            for run in runs_in(args.out_dir, args.backend):
                print(run, file=out)
            return 0
        if args.command == "run":
            result = summarise(args.run_dir, args.warmup_s)
            ok = result["trip_negative"] == 0
        elif args.command == "compare":
            result = compare([summarise(d, args.warmup_s) for d in args.baseline],
                             [summarise(d, args.warmup_s) for d in args.step],
                             args.added_ms, args.tolerance_ms)
            ok = result["ok"]
        elif args.command == "shakedown":
            wanted = tuple(c.strip() for c in args.checks.split(",") if c.strip())
            result = shakedown(args.pilot_dir, args.load_pct, args.load_points, wanted)
            ok = result["ok"]
        elif args.command == "paths":
            result = paths(args.pilot_dir, args.limit_ms)
            ok = result["ok"]
        else:
            result = go_first(args.table, args.factor)
            ok = result["ok"]
        print(json.dumps(result, indent=2, sort_keys=True), file=out)
        return 0 if ok else 1
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

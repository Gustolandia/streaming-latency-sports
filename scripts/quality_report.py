#!/usr/bin/env python3
"""
quality_report.py -- what a campaign's runs say about the instrument, once they are copied home.

This reads the conditions each run was meant to have and the instrument's own numbers. It does
not read whether a prediction came true: the law's own comparison stays sealed until the
campaigns are complete, because watching an answer arrive is what pre-registration exists to
prevent. Nothing here decides anything either. Every run keeps its verdict from the driver
(run_integrity.py); this only says what is worth a person's attention.

Per run it reports the verdict and its reasons, the messages kept, the send rate, the load, the
delay the broker held against the delay set, the clock offset, the CPU other tenants took, the
TCP segments each side sent again, and the pauses: messages that arrived more than STALL_MS after
they were sent, once the warm-up is past.

Per setup it makes the waypoint check. A setup's repeats are spread across a campaign on purpose,
in a shuffled order, so each one catches the machine in a different state. For each instrument
quantity the median over the repeats and a robust spread are taken (the median of the absolute
distances from the median, scaled to match a standard deviation), and a repeat is flagged when it lies
more than OUTLIER_Z of those away and at least a floor away in absolute terms. Flagged repeats are
registered with their numbers, and kept: a run whose conditions held is a result, whatever it
measured.

It also says what each run had cost. The campaign's queue records the moment it started every run,
and the watch's ledger (spend.py) records what had been spent at every moment it looked, so each
run carries the money that had gone by the time it began.

CLI:
    python scripts/quality_report.py --runs runs/azure/collected/matched/c0_.../runs
    python scripts/quality_report.py --runs <dir> --out report.json --no-stalls
    python scripts/quality_report.py --runs <dir> --ledger runs/azure_watch/spend.json
"""
import argparse
import csv
import glob
import io
import json
import os
import statistics
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spend  # noqa: E402

#: A message that arrives this long after it was sent, after the warm-up, is a pause worth noting.
STALL_MS = 150.0
#: How far from its fellows a repeat must lie to be flagged, in robust deviations.
OUTLIER_Z = 5.0
#: The quantities the waypoint check reads, with the absolute floor below which a difference is
#: too small to be worth anyone's attention.
WAYPOINT_FLOORS = {"trip_median_ms": 0.20, "gotit_median_ms": 0.20, "delay_held_ms": 0.05,
                   "load_pct": 1.0, "steal_pct": 1.0, "retransmitted_total": 5.0,
                   "stalls": 10.0}
#: 1 / 0.6745: the factor that makes the median absolute deviation match a standard deviation.
MAD_TO_SD = 1.4826


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def stalls(run_dir, warmup_s=30.0, limit_ms=STALL_MS):
    """(how many messages arrived more than limit_ms late, the worst one) after the warm-up."""
    sent = {}
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("t_prod_send_ns"):
                sent[row["event_id"]] = int(row["t_prod_send_ns"])
    if not sent:
        return 0, None
    cutoff = min(sent.values()) + int(warmup_s * 1e9)
    late, worst = 0, None
    name = "consumer_events.csv" if os.path.exists(
        os.path.join(run_dir, "consumer_events.csv")) else "consumer.csv"
    stamp = "t_consume_ns" if name == "consumer_events.csv" else "t_cons_recv_ns"
    with open(os.path.join(run_dir, name), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            start = sent.get(row.get("event_id"))
            if start is None or start < cutoff or not row.get(stamp):
                continue
            trip = (int(row[stamp]) - start) / 1e6
            if trip > limit_ms:
                late += 1
                worst = trip if worst is None else max(worst, trip)
    return late, worst


def one_run(run_dir, want_stalls=True, warmup_s=30.0):
    """Everything this report says about a single run."""
    found = {"run": os.path.basename(run_dir), "problems": []}
    try:
        row = read_json(os.path.join(run_dir, "queue_row.json"))
        params = row["params"] if isinstance(row["params"], dict) else json.loads(row["params"])
        found.update(setup=row.get("setup"), round=row.get("round"), backend=params.get("backend"),
                     delay_ms=float(params.get("delay_ms") or 0.0))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        found["problems"].append("the queue row could not be read: %s" % exc)
    try:
        judged = read_json(os.path.join(run_dir, "integrity.json"))
        checks, recorded = judged.get("checks", {}), judged.get("recorded", {})
        resent = recorded.get("retransmitted") or {}
        found.update(
            verdict=judged.get("verdict"), reasons=judged.get("reasons", []),
            messages=recorded.get("messages"), trip_median_ms=recorded.get("trip_median_ms"),
            gotit_median_ms=recorded.get("gotit_median_ms"),
            delay_held_ms=recorded.get("delay_held_ms"),
            steal_pct=recorded.get("steal_pct"),
            clock_offset_max_s=recorded.get("clock_offset_max_s"),
            send_rate=(checks.get("send_rate") or {}).get("value"),
            load_pct=(checks.get("load") or {}).get("value"),
            retransmitted_total=sum(v for v in resent.values() if isinstance(v, (int, float))) or 0)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        found["problems"].append("the verdict could not be read: %s" % exc)
    if want_stalls:
        try:
            found["stalls"], found["worst_trip_ms"] = stalls(run_dir, warmup_s)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            found["problems"].append("the messages could not be read: %s" % exc)
    return found


def waypoints(runs, floors=None, z=OUTLIER_Z):
    """Repeats of one setup, measured at different times, held against each other.

    Returns one entry per setup and quantity that had at least three repeats, with the median,
    the robust spread and any repeat far enough from its fellows to be worth a look.
    """
    floors = WAYPOINT_FLOORS if floors is None else floors
    by_setup = {}
    for run in runs:
        by_setup.setdefault(run.get("setup"), []).append(run)
    found = []
    for setup, repeats in sorted(by_setup.items(), key=lambda pair: str(pair[0])):
        for quantity, floor in sorted(floors.items()):
            values = [(r["run"], r[quantity]) for r in repeats
                      if isinstance(r.get(quantity), (int, float))]
            if len(values) < 3:
                continue
            numbers = [v for _, v in values]
            middle = statistics.median(numbers)
            spread = MAD_TO_SD * statistics.median([abs(v - middle) for v in numbers])
            far = []
            for name, value in values:
                distance = abs(value - middle)
                if distance < floor:
                    continue
                if spread == 0.0 or distance / spread > z:
                    far.append({"run": name, "value": value,
                                "distance_ms": distance,
                                "robust_z": None if spread == 0.0 else distance / spread})
            if far:
                found.append({"setup": setup, "quantity": quantity, "repeats": len(values),
                              "median": middle, "robust_spread": spread, "far": far})
    return found


def queue_rows(folder):
    """The campaign's queue rows: from a CSV beside the runs, or from the runs.tar packed with them.

    collect_runs.py copies the queue home with the runs it belongs to, so the moment the queue
    started each run travels with the data and needs nothing from the machines.
    """
    above = os.path.dirname(os.path.abspath(folder))
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))
                       + glob.glob(os.path.join(above, "*.csv"))):
        #: The folder above is whatever the runs were put in, and on a driver that was /tmp: a
        #: directory someone had named something.csv stopped the whole report, and any other
        #: CSV there would have been read as this campaign's queue. Only a file with the two
        #: columns this reads from a queue -- which run, and when it began -- is taken for one.
        if not os.path.isfile(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if rows and {"key", "started_utc"} <= set(rows[0]):
            return rows
    tar = os.path.join(above, "runs.tar")
    if os.path.exists(tar):
        with tarfile.open(tar) as archive:
            for member in archive.getmembers():
                if member.name.endswith(".csv"):
                    packed = archive.extractfile(member)
                    text = packed.read().decode("utf-8")
                    return list(csv.DictReader(io.StringIO(text)))
    return []


def money(runs, folder, ledger):
    """Give every run the moment the queue started it and what had been spent by then."""
    starts = dict((row["key"], row["started_utc"]) for row in queue_rows(folder)
                  if row.get("key") and row.get("started_utc"))
    for run in runs:
        for key, began in starts.items():
            if run["run"].endswith("_" + key):
                run["started_utc"] = began
                run["spent_usd_at_start"] = spend.at(ledger, began)
                break
    return runs


def report(run_dirs, want_stalls=True, warmup_s=30.0, ledger=None, folder=""):
    runs = [one_run(d, want_stalls, warmup_s) for d in run_dirs]
    if ledger is not None:
        money(runs, folder or os.path.dirname(run_dirs[0]), ledger)
    #: A campaign still running has a run with no verdict yet. Counted under None, it put a None
    #: key beside the string ones, and writing the report with sorted keys then failed -- so a
    #: report asked for mid-campaign, which is when it is most use, printed only an error.
    verdicts = {}
    for run in runs:
        said = run.get("verdict") or "not yet judged"
        verdicts[said] = verdicts.get(said, 0) + 1
    spreads = {}
    by_setup = {}
    for run in runs:
        if isinstance(run.get("trip_median_ms"), (int, float)):
            by_setup.setdefault(run.get("setup"), []).append(run["trip_median_ms"])
    for setup, trips in by_setup.items():
        if len(trips) > 1:
            spreads[setup] = {"runs": len(trips), "median_ms": statistics.median(trips),
                              "sd_ms": statistics.stdev(trips)}
    return {"runs": runs, "verdicts": verdicts, "setup_spread": spreads,
            "waypoints": waypoints(runs),
            "stalls_total": sum(r.get("stalls") or 0 for r in runs),
            "runs_with_problems": [r["run"] for r in runs if r["problems"]]}


def lines(found):
    """The report as a person reads it."""
    out = ["%d run(s): %s" % (len(found["runs"]),
                              ", ".join("%s %d" % (k, v) for k, v in sorted(
                                  found["verdicts"].items(), key=lambda p: str(p[0]))) or "none")]
    repeated = [r for r in found["runs"] if r.get("verdict") and r["verdict"] != "count"]
    for run in repeated:
        out.append("  %s: %s (%s)" % (run["verdict"], run["run"], "; ".join(run["reasons"])[:110]))
    for run in found["runs"]:
        for problem in run["problems"]:
            out.append("  unreadable: %s: %s" % (run["run"], problem))
    if found["stalls_total"]:
        worst = max((r.get("worst_trip_ms") or 0) for r in found["runs"])
        out.append("pauses over %g ms after the warm-up: %d message(s), worst %.0f ms"
                   % (STALL_MS, found["stalls_total"], worst))
    if found["setup_spread"]:
        widest = max(found["setup_spread"].items(), key=lambda pair: pair[1]["sd_ms"])
        out.append("run-to-run spread of the trip: widest %s at %.3f ms over %d runs"
                   % (widest[0], widest[1]["sd_ms"], widest[1]["runs"]))
    spent = [r["spent_usd_at_start"] for r in found["runs"]
             if isinstance(r.get("spent_usd_at_start"), (int, float))]
    if spent:
        out.append("money: these runs began between about $%.2f and $%.2f spent; about $%.2f went "
                   "on the campaign up to its last run" % (min(spent), max(spent),
                                                           max(spent) - min(spent)))
    if found["waypoints"]:
        out.append("repeats far from their fellows (registered, not removed):")
        for mark in found["waypoints"]:
            for far in mark["far"]:
                out.append("  %s %s: %s is %.3f from the median %.3f of %d repeats%s"
                           % (mark["setup"], mark["quantity"], far["run"], far["distance_ms"],
                              mark["median"], mark["repeats"],
                              "" if far["robust_z"] is None else
                              " (%.1f robust deviations)" % far["robust_z"]))
    else:
        out.append("no repeat lies far from its fellows")
    return out


def run_dirs_under(folder):
    """The run directories of a campaign, wherever they sit under `folder`."""
    found = [os.path.dirname(p) for p in
             glob.glob(os.path.join(folder, "**", "queue_row.json"), recursive=True)]
    return sorted(set(found))


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a campaign's runs say about the instrument")
    ap.add_argument("--runs", required=True, help="a folder holding the copied run directories")
    ap.add_argument("--out", default="", help="write the whole report here as JSON")
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--no-stalls", action="store_true", help="skip reading every message")
    ap.add_argument("--ledger", default=spend.LEDGER,
                    help="the watch's spending ledger, to say what each run began at")
    args = ap.parse_args(argv)
    try:
        dirs = run_dirs_under(args.runs)
        if not dirs:
            raise ValueError("no run directories under %s" % args.runs)
        found = report(dirs, not args.no_stalls, args.warmup_s, spend.load(args.ledger),
                       args.runs)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")
        for line in lines(found):
            print(line, file=out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

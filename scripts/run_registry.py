#!/usr/bin/env python3
"""
run_registry.py -- every run with the machine it ran on and the settings it ran under, and every
campaign with how far it got (plan version 32, D32-4).

Each run folder already says most of it. Its queue row gives the block, setup, round and settings
it was designed with; its integrity record the verdict, the trip, the negative rate, the delay the
broker held and what the got-it brake said; its lane the pair, the driver and the commit; and the
scheduler's own reading before it ran the kernel, the tick, the CPU model, the CPUs online and the
slice in force. The machine sizes and images come from cloud/azure/testbed.json, where the pairs
were made. A campaign's own folder holds its queue, which says how many of its runs were done,
which failed and were run again, and which were never reached, and its log, whose last line says
how it ended. This gathers all of it into one row per run and one row per campaign, so that what
ran, where and how, can be read without the run folders.

CLI:
    python scripts/run_registry.py --runs <folder> [--runs ...] --out runs.csv
        [--campaigns <stage1 folder> --campaigns-out campaigns.csv] [--spec testbed.json]
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_report  # noqa: E402

SPEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "cloud", "azure", "testbed.json")
RUN_FIELDS = (
    "run", "campaign", "pair", "driver", "driver_size", "broker_size", "image", "commit",
    "block", "setup", "round", "attempt", "backend", "load_pct", "slice_set_ns", "point",
    "delay_set_ms", "delay_held_ms", "ack_batch", "cpus", "language", "priority",
    "consumer_priority", "recv_capture", "plan", "recorded_half", "kernel", "config_hz",
    "tick_ms", "cpu_model", "online_cpus", "slice_in_force_ns", "clocksource", "verdict",
    "trip_median_ms", "gotit_median_ms", "measured_negative_rate", "messages", "gotit_brake",
    "reasons")
CAMPAIGN_FIELDS = (
    "campaign", "folder", "block", "kernel", "cpu_model", "online_cpus", "designed_runs", "done",
    "left", "failed_attempts", "abandoned", "complete", "ended", "first_started_utc",
    "last_finished_utc")
#: The settings a queue row's params carry. R1 (3 Oct 2026) added go-first for the consumer
#: alone and the receiver's full capture; no earlier block sets either.
PLAN_KEYS = ("backend", "load_pct", "point", "ack_batch", "cpus", "language", "priority",
             "consumer_priority", "recv_capture", "plan")


def _json(path):
    try:
        return quality_report.read_json(path)
    except (OSError, ValueError):
        return {}


def machines(spec_path=SPEC):
    """{driver host: (driver size, broker size, image)} from the testbed's own specification."""
    spec = _json(spec_path)
    hosts, found = spec.get("hosts") or {}, {}
    for profile in (spec.get("profiles") or {}).values():
        names = profile.get("hosts") or []
        roles = dict((hosts.get(n, {}).get("role"), n) for n in names)
        driver, broker = roles.get("driver"), roles.get("broker")
        if driver:
            found[driver] = (hosts[driver].get("size"), hosts.get(broker, {}).get("size"),
                             (spec.get("images") or {}).get(hosts[driver].get("image"),
                                                            hosts[driver].get("image")))
    return found


def campaign_of(run_name, key=None):
    """The campaign label a run folder's name carries: law_<block>_<stamp>_<key>. A queue named
    without a stamp, as R1's r1 was (3 October), leaves law_<queue>_<key>, and then the run's own
    key says where the queue's name ends."""
    parts = run_name.split("_")
    if len(parts) > 3 and parts[0] == "law":
        return "_".join(parts[1:3])
    if key and run_name.startswith("law_") and run_name.endswith("_" + key) \
            and len(run_name) > len(key) + 5:
        return run_name[4:-len(key) - 1]
    return ""


def run_row(run_dir, sizes):
    """One run's row, or None where the folder is not a run's."""
    row = _json(os.path.join(run_dir, "queue_row.json"))
    if not row:
        return None
    params = row.get("params") or {}
    if isinstance(params, str):
        params = json.loads(params)
    judged = _json(os.path.join(run_dir, "integrity.json"))
    recorded = judged.get("recorded") or {}
    lane = _json(os.path.join(run_dir, "lane.json"))
    settings = _json(os.path.join(run_dir, "settings_before.json")).get("settings") or {}
    driver = lane.get("driver") or ""
    size = sizes.get(driver, (None, None, None))
    name = os.path.basename(run_dir.rstrip("/\\"))
    found = {"run": name, "campaign": campaign_of(name, row.get("key")),
             "pair": lane.get("lane") or lane.get("profile") or "", "driver": driver,
             "driver_size": size[0], "broker_size": size[1], "image": size[2],
             "commit": (lane.get("commit") or "")[:12],
             "block": params.get("block") or str(row.get("setup") or "").split("-")[0],
             "setup": row.get("setup"), "round": row.get("round"), "attempt": row.get("attempt"),
             "slice_set_ns": params.get("slice_ns"), "delay_set_ms": params.get("delay_ms"),
             "delay_held_ms": recorded.get("delay_held_ms"),
             "recorded_half": bool(params.get("trace_half")) and os.path.exists(
                 os.path.join(run_dir, "runqlat.txt")) or os.path.exists(
                 os.path.join(run_dir, "waits.txt")),
             "kernel": settings.get("release"), "config_hz": settings.get("config_hz"),
             "tick_ms": settings.get("tick_ms"), "cpu_model": settings.get("cpu_model"),
             "online_cpus": settings.get("online_cpus"),
             "slice_in_force_ns": settings.get("base_slice_ns"),
             "clocksource": settings.get("clocksource"), "verdict": judged.get("verdict"),
             "trip_median_ms": recorded.get("trip_median_ms"),
             "gotit_median_ms": recorded.get("gotit_median_ms"),
             "measured_negative_rate": recorded.get("measured_negative_rate"),
             "messages": recorded.get("messages"), "gotit_brake": recorded.get("gotit_brake"),
             "reasons": "; ".join(str(r) for r in judged.get("reasons") or [])}
    found.update((key, params.get(key)) for key in PLAN_KEYS)
    return found


def campaign_row(folder):
    """One campaign's row from its own folder: its queue, its settings and its log."""
    queues = sorted(glob.glob(os.path.join(folder, "*_20*.csv")))
    if not queues:
        return None
    with open(queues[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    count = dict((s, sum(1 for r in rows if r.get("status") == s))
                 for s in ("done", "queued", "running", "failed", "abandoned"))
    settings = _json(os.path.join(folder, "settings.json"))
    logs = sorted(glob.glob(os.path.join(folder, "campaign_*.log")))
    last = ""
    if logs:
        with open(logs[0], encoding="utf-8", errors="replace") as fh:
            lines = [line.strip() for line in fh if line.strip()]
        last = lines[-1] if lines else ""
    ended = ("complete" if "CAMPAIGN_COMPLETE" in last else "stopped: " + last.split(
        "STOP_RULE:", 1)[1].strip()[:160] if "STOP_RULE:" in last else "stopped by hand"
             if "STOPPED at" in last else "not ended")
    started = sorted(r["started_utc"] for r in rows if r.get("started_utc"))
    finished = sorted(r["finished_utc"] for r in rows if r.get("finished_utc"))
    left = count["queued"] + count["running"]
    return {"campaign": os.path.basename(queues[0])[:-4], "folder": os.path.basename(
                folder.rstrip("/\\")),
            "block": os.path.basename(queues[0]).split("_")[0].upper(),
            "kernel": settings.get("release"), "cpu_model": settings.get("cpu_model"),
            "online_cpus": settings.get("online_cpus"),
            "designed_runs": count["done"] + left + count["abandoned"], "done": count["done"],
            "left": left, "failed_attempts": count["failed"], "abandoned": count["abandoned"],
            "complete": left == 0 and count["abandoned"] == 0, "ended": ended,
            "first_started_utc": started[0] if started else "",
            "last_finished_utc": finished[-1] if finished else ""}


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict((key, row.get(key)) for key in fields))


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Every run with its machine and settings, and every "
                                             "campaign with how far it got")
    ap.add_argument("--runs", action="append", default=[], help="a folder holding run folders")
    ap.add_argument("--out", default="", help="the runs' registry, as CSV")
    ap.add_argument("--campaigns", action="append", default=[],
                    help="a folder holding campaign folders (runs/azure/stage1)")
    ap.add_argument("--campaigns-out", default="")
    ap.add_argument("--spec", default=SPEC)
    args = ap.parse_args(argv)
    if not (args.runs and args.out) and not (args.campaigns and args.campaigns_out):
        print("ERROR: give --runs with --out, or --campaigns with --campaigns-out", file=out)
        return 2
    if args.runs and args.out:
        sizes = machines(args.spec)
        rows = [row for folder in args.runs
                for row in (run_row(d, sizes) for d in quality_report.run_dirs_under(folder))
                if row is not None]
        write(args.out, RUN_FIELDS, sorted(rows, key=lambda r: r["run"]))
        print("%d runs -> %s" % (len(rows), args.out), file=out)
    if args.campaigns and args.campaigns_out:
        rows = [row for folder in args.campaigns
                for row in (campaign_row(d) for d in sorted(glob.glob(os.path.join(folder, "*/"))))
                if row is not None]
        write(args.campaigns_out, CAMPAIGN_FIELDS, rows)
        unfinished = [r for r in rows if not r["complete"]]
        print("%d campaigns, %d complete, %d with runs left -> %s"
              % (len(rows), len(rows) - len(unfinished), len(unfinished), args.campaigns_out),
              file=out)
        for row in unfinished:
            print("  %s: %d of %d done, %d left (%s)" % (
                row["folder"], row["done"], row["designed_runs"], row["left"], row["ended"]),
                file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

#!/usr/bin/env python3
"""
so_fix.py -- freeze 40's test of the full fix in the form a benchmark tool would use: the kernel's
own timestamps, read by the producer and the consumer on their broker connections through
SO_TIMESTAMPING (scripts/so_timestamps.py), against the packet captures F1 read them from.

Per message, on the driver's one clock: t_pub, t_tx, t_rx and t_recv as scripts/full_fix.py reads
them, and

  t_tx_so  the kernel's transmit timestamp of the producer's send call that carried the end of the
           message's event id (producer_so.csv);
  t_rx_so  the kernel's receive timestamp of the consumer's read that delivered it
           (consumer_so.csv).

  W     = t_rx - t_tx         F1's kernel-timed latency, from the captures: the reference;
  W_so  = t_rx_so - t_tx_so   the same latency as a tool reads it.

G-a is judged on |W_so - W|, message by message; G-b to G-e repeat F1's F-a to F-d with W_so in
place of W. A pause is marked as F1 marks it.

CLI:
    python scripts/so_fix.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --out CSV
    python scripts/so_fix.py judge --table CSV --out JSON
"""
import argparse
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_fix as ff  # noqa: E402
import quality_report  # noqa: E402
import recv_wait as rw  # noqa: E402

#: The block's setups, by the prefix of their ids in the queue.
SETUP = "F2-"
#: G-a: how far W_so may lie from W, in microseconds: a setup's median of each run's median of
#: |W_so - W|, and of each run's 99th percentile of it.
AGREE_MEDIAN_US = 20.0
AGREE_TAIL_US = 100.0

STATS = ff.STATS
FIELDS = (("run", "setup", "backend", "load_pct", "priority", "load_measured", "dropped",
           "stamped", "messages", "so_messages", "so_missing_tx", "so_missing_rx",
           "so_nonpositive", "agreed", "D_max", "D_held", "Wso_held")
          + tuple("%s_%s" % (span, stat) for span in ("D", "W", "Wso", "Dif") for stat in STATS)
          # Described, not judged: where the two instruments' timestamps differ, and how often the
          # receive timestamps are the very same.
          + ("tx_diff_median", "tx_diff_p99", "rx_diff_median", "rx_diff_p99", "rx_same_share"))


def socket_times(run_dir):
    """({event id: t_tx_so}, {event id: t_rx_so}) from the two clients' socket files, the ids a
    timestamp covers only; ({}, {}) for a file the run did not write."""
    out = []
    for name, way in (("producer_so.csv", "tx"), ("consumer_so.csv", "rx")):
        found = {}
        path = os.path.join(run_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row["direction"] == way and row["ns"]:
                        found[row["event_id"]] = int(row["ns"])
        out.append(found)
    return out[0], out[1]


def _spans(name, values, out):
    out[name + "_min"] = min(values) if values else None
    out[name + "_median"] = statistics.median(values) if values else None
    out[name + "_mean"] = statistics.fmean(values) if values else None
    out[name + "_p99"] = rw.percentile(values, 99) if values else None


def read_run(run_dir, driver, broker, receiver):
    """One run's spans and the two instruments' agreement, in microseconds."""
    row = rw.read_json(os.path.join(run_dir, "queue_row.json"))
    params = row.get("params") or {}
    judged = rw.read_json(os.path.join(run_dir, "integrity.json"))
    msgs = rw.messages(run_dir)
    found, stamped, missed_tx, missed_rx = ff.times(run_dir, driver, broker, receiver)
    so_tx, so_rx = socket_times(run_dir)
    out = {"run": os.path.basename(run_dir), "setup": row.get("setup"),
           "backend": params.get("backend"), "load_pct": params.get("load_pct"),
           "priority": bool(params.get("priority")),
           "load_measured": ((judged.get("checks") or {}).get("load") or {}).get("value"),
           "dropped": ff.capture_drops(run_dir), "stamped": stamped, "messages": len(found),
           "so_missing_tx": sum(1 for eid, _, _ in msgs if eid not in so_tx),
           "so_missing_rx": sum(1 for eid, _, _ in msgs if eid not in so_rx)}
    both = [(eid, pub, recv) for eid, pub, recv in msgs if eid in so_tx and eid in so_rx]
    out["so_messages"] = len(both)
    wso = [(so_rx[eid] - so_tx[eid]) / 1e3 for eid, _, _ in both]
    out["so_nonpositive"] = sum(1 for w in wso if w <= 0)
    agreed = [(eid, tx, rx) for eid, _, tx, rx, _ in found if eid in so_tx and eid in so_rx]
    out["agreed"] = len(agreed)
    tx_diff = [(so_tx[eid] - tx) / 1e3 for eid, tx, _ in agreed]
    rx_diff = [(so_rx[eid] - rx) / 1e3 for eid, _, rx in agreed]
    dif = [abs(r - t) for t, r in zip(tx_diff, rx_diff)]
    spans = {"D": [(recv - pub) / 1e3 for _, pub, recv in msgs],
             "W": [(rx - tx) / 1e3 for _, _, tx, rx, _ in found], "Wso": wso, "Dif": dif}
    for name, values in spans.items():
        _spans(name, values, out)
    # A pause holds every message sent while it lasts and releases them together; marked as F1
    # marks it, by the quality report's limit, in D and in W_so.
    limit = quality_report.STALL_MS * 1e3
    out["D_max"] = max(spans["D"]) if spans["D"] else None
    out["D_held"] = sum(1 for d in spans["D"] if d > limit)
    out["Wso_held"] = sum(1 for w in wso if w > limit)
    for name, values in (("tx_diff", tx_diff), ("rx_diff", rx_diff)):
        out[name + "_median"] = statistics.median(values) if values else None
        out[name + "_p99"] = rw.percentile(values, 99) if values else None
    out["rx_same_share"] = (sum(1 for d in rx_diff if d == 0) / float(len(rx_diff))
                            if rx_diff else None)
    return out


def agreement(rows):
    """G-a: in every setup, the median over its runs of each run's median |W_so - W| at most
    AGREE_MEDIAN_US, and of each run's 99th percentile of it at most AGREE_TAIL_US."""
    results, shown = [], {}
    for b in ff.BACKENDS:
        for load in (ff.IDLE, ff.BUSY):
            for p in (False, True):
                med = ff.setup_value(rows, b, load, p, "Dif_median")
                tail = ff.setup_value(rows, b, load, p, "Dif_p99")
                results.append(None if med is None or tail is None
                               else med <= AGREE_MEDIAN_US and tail <= AGREE_TAIL_US)
                shown["%s, %d%% load, %s priority" % (b, load, "real-time" if p else "normal")] = (
                    med, tail)
    return {"verdict": ff._verdict(results), "values": shown}


def nothing_lost(rows):
    """G-d: no W_so at or below zero, and under UNMATCHED_SHARE of each run's messages missing
    either socket timestamp."""
    bad = [r["run"] for r in rows
           if int(r["so_nonpositive"]) or not int(r["stamped"])
           or max(int(r["so_missing_tx"]), int(r["so_missing_rx"]))
           > ff.UNMATCHED_SHARE * int(r["stamped"])]
    return {"verdict": "holds" if rows and not bad else ("fails" if bad else "undecided"),
            "runs_against": bad}


def judge(rows):
    return {"G-a": agreement(rows),
            "G-b": ff.held_still(rows, "Wso_median", ff.MEDIAN_SHARE),
            "G-c": ff.held_still(rows, "Wso_p99", ff.TAIL_SHARE),
            "G-d": nothing_lost(rows), "G-e": ff.the_hosts_effect(rows, wire="Wso_mean")}


def pauses(rows):
    """The runs a pause held messages in: [run, setup, messages held in D, in W_so, D's largest]."""
    return [[r["run"], r["setup"], int(float(r["D_held"])), int(float(r["Wso_held"])),
             float(r["D_max"])] for r in rows if int(float(r.get("D_held") or 0))]


def read_block(folders, driver, broker, receiver, setup=SETUP):
    """(rows for the runs the integrity rule passed, [(run, verdict)] for the others)."""
    rows, skipped = [], []
    for run_dir, verdict in ff.block_runs(folders, setup):
        if verdict != rw.PASSING:
            skipped.append((os.path.basename(run_dir), verdict or "not judged"))
            continue
        rows.append(read_run(run_dir, driver, broker, receiver))
    return rows, skipped


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze 40's test of the full fix as a tool reads it")
    sub = ap.add_subparsers(dest="cmd", required=True)
    read = sub.add_parser("read", help="each passing run's spans, from its captures and sockets")
    read.add_argument("--runs", action="append", required=True)
    for name in ("--driver", "--broker", "--receiver", "--out"):
        read.add_argument(name, required=True)
    judged = sub.add_parser("judge", help="G-a to G-e, from the table read writes")
    judged.add_argument("--table", required=True)
    judged.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        rows, skipped = read_block(args.runs, args.driver, args.broker, args.receiver)
        if not rows:
            print("no passing run of the block under %s" % ", ".join(args.runs))
            return 1
        write_csv(args.out, rows)
        print("%d runs read; left out: %s" % (len(rows), skipped or "none"))
        return 0
    with open(args.table, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    found, held = judge(rows), pauses(rows)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(dict(found, pauses=held), fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(found):
        print("%s  %s" % (name, found[name]["verdict"]))
    print("runs a pause held messages in: %d" % len(held))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

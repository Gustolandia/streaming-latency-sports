#!/usr/bin/env python3
"""
backlog_census.py
The two consumer faults of the July cloud testbed, counted run by run over Table I's corpus.

1. The consumer stopped during long pauses. scripts/kafka_consumer.py and
   scripts/redis_consumer.py stop after --idle-seconds (15) with no message. The producer
   replays a match in real time, and a match that pauses for longer than that stops the
   consumer; the producer publishes the rest to a broker that acknowledges it and that no one
   reads. `published - consumed` counts those messages.

2. The consumer first read earlier campaigns' messages. The runs reused topic and stream names
   and nothing cleared them (stale_backlog.py says how), so a run's first messages waited while
   its consumer read other runs'. `late` counts the run's messages stale_backlog.late flags;
   `neg_late` how many of those have S below zero, which the rule's argument says is none;
   `first_waited` whether the run's first published message was itself delivered more than
   the margin after the fastest, as a backlog at the run's start makes it; and, for Redis,
   whose consumer logs every read, `foreign_read` how many other runs' messages it read.
   `negatives` counts the run's matched messages with S below zero, and `fastest_ms` is its
   fastest delivery, from which the rule measures.

A backlog read in under a second escapes the rule, which needs a wait of a second to see one.
`late_wide` and `neg_wide` count what a wider rule would leave out, the rule's own messages and
the start-up waits wider() finds, so that the supplement can say how much the narrower rule's
choice moves the rate. They are a check; no analysis leaves those messages out.

The raw archive is not tracked, so the table is (docs/results/backlog_by_run.csv), and the
supplement's account of both faults is emitted from it. The same count over the registered
Azure campaign's runs, which are not tracked either, is docs/results/backlog_azure_by_run.csv:
that campaign deleted its streams and topics before each run, and the count shows how far that
held.

CLI:
    python scripts/backlog_census.py --runs-dir cloud_archive/extracted/runs
    python scripts/backlog_census.py --runs-dir runs/azure/final_tree/arm/runs \
        --runs-dir runs/azure/final_tree/matched/runs \
        --runs-dir runs/azure/final_tree/matched-b/runs \
        --out docs/results/backlog_azure_by_run.csv
"""
import argparse
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stale_backlog  # noqa: E402

DEFAULT_OUT = os.path.join("docs", "results", "backlog_by_run.csv")
FIELDS = ("run_id", "backend", "published", "consumed", "joined", "fastest_ms", "negatives",
          "late", "neg_late", "first_waited", "late_wide", "neg_wide", "foreign_read")
#: How far above its run's median S a kept message at the run's start may lie before the check
#: in wider() counts it as a start-up wait, in ms.
WIDE_MARGIN_MS = 300.0


def _read(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def wider(joined, flags):
    """The start-up waits the rule keeps, for a check of how much they matter; not a rule.

    joined holds (publish ns, receipt ns, S ns) in publish order and flags the rule's verdicts.
    Of the messages the rule keeps, the leading ones whose S exceeds the kept messages' median
    S by more than WIDE_MARGIN_MS, and every kept message published before the last of them was
    received, are flagged.
    """
    kept = [j for j, f in zip(joined, flags) if not f]
    if not kept:
        return [False] * len(joined)
    median = statistics.median(s for _, _, s in kept)
    k = 0
    while k < len(kept) and kept[k][2] > median + WIDE_MARGIN_MS * 1e6:
        k += 1
    if not k:
        return [False] * len(joined)
    caught_up = max(r for _, r, _ in kept[:k])
    return [not f and p < caught_up for (p, _, _), f in zip(joined, flags)]


def census(run_id, backend, run_dir):
    """One run's row."""
    prod_rows = _read(os.path.join(run_dir, "producer.csv"))
    prod = {r["event_id"]: r for r in prod_rows}
    cons = _read(os.path.join(run_dir, "consumer.csv"))
    late_ids = stale_backlog.late_ids(prod_rows, cons)
    joined = []
    for c in cons:
        p = prod.get(c["event_id"])
        if p and p["t_broker_ack_ns"] and p["t_prod_send_ns"] and c["t_cons_recv_ns"]:
            recv = int(c["t_cons_recv_ns"])
            joined.append((int(p["t_prod_send_ns"]), recv, recv - int(p["t_broker_ack_ns"]),
                           c["event_id"] in late_ids))
    joined.sort()
    flags = [is_late for _, _, _, is_late in joined]
    spans = [s for _, _, s, _ in joined]
    deliveries = [(r - p) / 1e6 for p, r, _, _ in joined]
    n_late = sum(flags)
    first = ""
    if n_late:
        # A backlog at the run's start delays its first message most; a wait in mid-run would
        # leave it prompt.
        first = int(deliveries[0] > min(deliveries) + stale_backlog.LATE_MARGIN_MS
                    or min(deliveries) > stale_backlog.LATE_MARGIN_MS)
    extra = wider([j[:3] for j in joined], flags)
    foreign = ""
    trace = os.path.join(run_dir, "consumer_readtrace.csv")
    if os.path.exists(trace):
        foreign = sum(int(r["n_messages"]) for r in _read(trace)) - len(cons)
    return {"run_id": run_id, "backend": backend, "published": len(prod),
            "consumed": len(cons), "joined": len(joined),
            "fastest_ms": "%.3f" % min(deliveries) if deliveries else "",
            "negatives": sum(1 for s in spans if s < 0), "late": n_late,
            "neg_late": sum(1 for f, s in zip(flags, spans) if f and s < 0),
            "first_waited": first, "late_wide": n_late + sum(extra),
            "neg_wide": sum(1 for f, e, s in zip(flags, extra, spans) if (f or e) and s < 0),
            "foreign_read": foreign}


def backend_of(run_dir):
    """meta.json's backend, as recount_spans reads it."""
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as fh:
        return json.load(fh)["backend"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="The July testbed's consumer faults, run by run")
    ap.add_argument("--runs-dir", action="append",
                    help="a folder of run folders; give it once per folder (default: the July "
                         "archive's)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    folders = args.runs_dir or [os.path.join("cloud_archive", "extracted", "runs")]
    missing = [f for f in folders if not os.path.isdir(f)]
    if missing:
        print("missing: %s" % ", ".join(missing))
        return 1
    # Every run with a matched message, before any is left out: Table I's corpus as it was
    # counted before the late messages were, so that a run left with none still appears.
    rows = []
    for folder in folders:
        for run_id in sorted(os.listdir(folder)):
            run_dir = os.path.join(folder, run_id)
            if not all(os.path.exists(os.path.join(run_dir, f))
                       for f in ("producer.csv", "consumer.csv", "meta.json")):
                continue
            row = census(run_id, backend_of(run_dir), run_dir)
            if row["joined"]:
                rows.append(row)
    if not rows:
        print("no run in %s has a matched message -- refusing to write" % ", ".join(folders))
        return 1
    folder = os.path.dirname(args.out)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print("wrote %s (%d runs)" % (args.out, len(rows)))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())

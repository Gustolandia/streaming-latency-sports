#!/usr/bin/env python3
"""
analyze_m1_client.py
Decide whether the paper's ~103 ms producer scheduling-lag offset belongs to Kafka or to the
kafka-python client library.

The paper reports that Kafka's end-to-end delay at football's sparse arrival rate is ~105 ms of
which ~103 ms is producer scheduling lag -- the interval between an event's planned emission and
the producer issuing the send. Three measured properties (constant, concurrency-invariant,
rate-dependent) point at a client sender thread waking from idle, but that was an inference.
Section 7.2 says "inferred, comparison in progress".

This runs the comparison: the identical experiment against a second, independently implemented
client (confluent-kafka / librdkafka). If the offset vanishes with the other client, it is a
library property and the paper's practical recommendation must be restated. If it persists, it
is a property of how Kafka producers behave on a sparse feed.

Reads the per-event loop traces (--trace-loop) which split the lag into:
    wake_late_ms  how late the sleep returned relative to planned emission
    produce_ms    how long the send call itself blocked

CLI:
    python scripts/analyze_m1_client.py --m1-dir docs/results/m1_client
"""
import argparse
import csv
import glob
import os
import statistics as st
from pathlib import Path


def load_trace(path):
    """(wake_late_ms, produce_ms) lists from one trace file."""
    wake, prod = [], []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    wake.append(float(r["wake_late_ms"]))
                    prod.append(float(r["produce_ms"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return [], []
    return wake, prod


def client_stats(m1_dir, client):
    """Pooled loop statistics for one client across all its replicate traces."""
    wake, prod, files = [], [], 0
    for path in sorted(glob.glob(os.path.join(m1_dir, f"trace_{client}_*.csv"))):
        w, p = load_trace(path)
        if w:
            wake.extend(w)
            prod.extend(p)
            files += 1
    if not wake:
        return None
    wake_sorted = sorted(wake)
    return {
        "client": client,
        "files": files,
        "events": len(wake),
        "wake_late_p50": st.median(wake),
        "wake_late_p95": wake_sorted[min(len(wake_sorted) - 1, int(len(wake_sorted) * 0.95))],
        "wake_late_max": max(wake),
        "produce_p50": st.median(prod) if prod else float("nan"),
    }


def verdict(a, b, threshold_ms=50.0):
    """Is the large offset present in both clients, or only one?

    `threshold_ms` is deliberately far below the ~103 ms in question and far above the
    sub-millisecond baseline, so the classification is not sensitive to its exact value.
    """
    big_a = a["wake_late_p95"] >= threshold_ms
    big_b = b["wake_late_p95"] >= threshold_ms
    if big_a and big_b:
        return ("BOTH", "the offset appears in both clients: it is a property of how Kafka "
                        "producers behave on a sparse feed, not of one library")
    if big_a != big_b:
        only = a["client"] if big_a else b["client"]
        return ("ONE", f"the offset appears only in {only}: it is a library property, and the "
                       f"paper's end-to-end comparison is a statement about that client")
    return ("NEITHER", "neither client shows the offset in this run; the earlier measurement "
                       "is not reproduced and must be re-examined")


def main(argv=None):
    ap = argparse.ArgumentParser(description="M1: is the producer offset Kafka or kafka-python?")
    ap.add_argument("--m1-dir", default="docs/results/m1_client")
    ap.add_argument("--threshold-ms", type=float, default=50.0)
    args = ap.parse_args(argv)

    if not Path(args.m1_dir).is_dir():
        print(f"missing M1 directory: {args.m1_dir}")
        return 1

    stats = [s for s in (client_stats(args.m1_dir, c)
                         for c in ("kafka-python", "confluent")) if s]
    if len(stats) < 2:
        got = [s["client"] for s in stats]
        print(f"need both clients, found: {got or 'none'}")
        return 1

    print("== M1: producer loop timing by client (N=1, true real time) ==")
    for s in stats:
        print(f"  {s['client']:13s} traces={s['files']} events={s['events']:5d}  "
              f"wake_late p50={s['wake_late_p50']:8.3f} ms  p95={s['wake_late_p95']:8.3f} ms  "
              f"max={s['wake_late_max']:8.1f} ms  produce p50={s['produce_p50']:.3f} ms")

    tag, explanation = verdict(stats[0], stats[1], args.threshold_ms)
    print(f"\n== VERDICT: {tag} ==")
    print(f"  {explanation}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())

#!/usr/bin/env python3
"""
analyze_e1_replication.py
The pre-registered analysis for E1-REP (referee issue M2): does the E1/powered discrepancy come
from measuring different EVENTS rather than different systems?

The paper reports two transport measurements that cannot both describe the same brokers. E1 finds
them near-equal (Kafka 0.79-1.00 ms against Redis 0.72-0.86 ms); a powered replication finds Kafka
0.54 ms against Redis 0.11 ms. Our hypothesis is that E1 matched a median of seven events per run,
and those seven are the opening burst -- the events queued behind Kafka's blocking first send and
released together when it resolves. Transport over a batch-released burst need not resemble
transport over 127 events in steady state.

That predicts something sharp, and this script tests it on one campaign so the comparison is not
confounded by anything else. From the SAME runs we compute transport two ways:

  ALL events               -> should reproduce the powered result (Kafka slower by ~0.4 ms)
  FIRST SEVEN events only  -> should reproduce E1's near-equality

If both hold, the discrepancy is explained and E1's numbers are re-labelled rather than withdrawn.
If the first-seven subset does NOT reproduce E1, the hypothesis is wrong, we have a second
unexplained instability, and the paper must withdraw E1's transport row instead. The script
reports which of those happened; it does not decide in advance.

CLI:
    python scripts/analyze_e1_replication.py --rep-dir docs/results/e1_rep --runs-dir runs \
        --out docs/results/e1_rep
"""
import argparse
import csv
import glob
import os
import re
import statistics as st
from pathlib import Path

PROLOGUE_EVENTS = 7          # E1's median matched count
NEAR_EQUAL_MS = 0.20         # E1's shifts wandered between 0.021 and 0.116 ms
POWERED_SHIFT_MS = 0.41      # the powered replication's Hodges-Lehmann shift


def condition_timestamp(cond_dir):
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def run_transports(run_dir):
    """Per-event transport (ms) for one run, in emission order.

    Emission order is what makes the prologue subset meaningful: the first seven events of a run
    are the ones E1 was measuring, so they must be taken in the order the producer emitted them
    rather than the order the consumer happened to write them.
    """
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return []
    ack, order = {}, {}
    try:
        with open(prod, newline="", encoding="utf-8") as fh:
            for i, r in enumerate(csv.DictReader(fh)):
                v = r.get("t_broker_ack_ns")
                if v not in (None, "", "None"):
                    ack[r["event_id"]] = int(v)
                    order[r["event_id"]] = i
        rows = []
        with open(cons, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a = ack.get(r["event_id"])
                rc = r.get("t_consume_ns")
                if a is not None and rc not in (None, "", "None"):
                    rows.append((order.get(r["event_id"], 0), (int(rc) - a) / 1e6))
    except (ValueError, KeyError, OSError):
        return []
    rows.sort()
    return [t for _, t in rows]


def condition_medians(cond_dir, runs_dir, backend, prologue=PROLOGUE_EVENTS):
    """Per-run median transport, computed over all events and over the prologue only."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return [], []
    all_med, pro_med = [], []
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
        series = run_transports(run)
        if not series:
            continue
        all_med.append(st.median(series))
        head = series[:prologue]
        if head:
            pro_med.append(st.median(head))
    return all_med, pro_med


def collect(rep_dir, runs_dir, prologue=PROLOGUE_EVENTS):
    rows = []
    for cond in sorted(glob.glob(os.path.join(rep_dir, "n*"))):
        if not os.path.isdir(cond):
            continue
        m = re.search(r"n(\d+)$", os.path.basename(cond))
        if not m:
            continue
        cells = {}
        for backend in ("kafka", "redis"):
            a, p = condition_medians(cond, runs_dir, backend, prologue)
            if a and p:
                cells[backend] = (a, p)
        if len(cells) == 2:
            rows.append({
                "n_feeds": int(m.group(1)),
                "n_runs": min(len(cells["kafka"][0]), len(cells["redis"][0])),
                "kafka_all": round(st.median(cells["kafka"][0]), 4),
                "redis_all": round(st.median(cells["redis"][0]), 4),
                "kafka_prologue": round(st.median(cells["kafka"][1]), 4),
                "redis_prologue": round(st.median(cells["redis"][1]), 4),
            })
    for r in rows:
        r["shift_all"] = round(r["kafka_all"] - r["redis_all"], 4)
        r["shift_prologue"] = round(r["kafka_prologue"] - r["redis_prologue"], 4)
    return sorted(rows, key=lambda r: r["n_feeds"])


def verdict(rows, near_equal=NEAR_EQUAL_MS, powered=POWERED_SHIFT_MS, tol=0.5):
    """Did measuring different events explain the discrepancy?"""
    if not rows:
        return {"testable": False, "explained": False,
                "why": "no condition has both backends"}
    all_shifts = [r["shift_all"] for r in rows]
    pro_shifts = [r["shift_prologue"] for r in rows]
    med_all, med_pro = st.median(all_shifts), st.median(pro_shifts)
    # All-events must land near the powered result; prologue-only must collapse toward E1.
    all_ok = abs(med_all - powered) <= tol * powered
    pro_ok = abs(med_pro) <= near_equal
    return {
        "testable": True,
        "median_shift_all": round(med_all, 4),
        "median_shift_prologue": round(med_pro, 4),
        "all_reproduces_powered": bool(all_ok),
        "prologue_reproduces_e1": bool(pro_ok),
        "explained": bool(all_ok and pro_ok),
        "why": ("measuring the opening burst instead of the whole run accounts for the "
                "difference: the same runs give the powered shift over all events and E1's "
                "near-equality over the first seven"
                if all_ok and pro_ok else
                "the prologue subset does not reproduce E1's near-equality, so the "
                "discrepancy is NOT explained by which events were measured"
                if all_ok and not pro_ok else
                "all-event transport does not reproduce the powered result, so this campaign "
                "does not replicate the measurement it was meant to replicate"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="E1 replication: does event selection explain it?")
    ap.add_argument("--rep-dir", default="docs/results/e1_rep")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--prologue", type=int, default=PROLOGUE_EVENTS)
    ap.add_argument("--out", default="docs/results/e1_rep")
    args = ap.parse_args(argv)

    if not Path(args.rep_dir).is_dir():
        print(f"missing replication directory: {args.rep_dir}")
        return 1
    rows = collect(args.rep_dir, args.runs_dir, args.prologue)
    if not rows:
        print("no usable conditions")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fields = ["n_feeds", "n_runs", "kafka_all", "redis_all", "shift_all",
              "kafka_prologue", "redis_prologue", "shift_prologue"]
    with (out / "e1_replication.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"== E1 replication: transport over all events vs the first {args.prologue} ==")
    for r in rows:
        print(f"  N={r['n_feeds']:2d} runs={r['n_runs']:3d}  "
              f"all: kafka {r['kafka_all']:.3f} redis {r['redis_all']:.3f} "
              f"shift {r['shift_all']:+.3f}  |  "
              f"first{args.prologue}: kafka {r['kafka_prologue']:.3f} "
              f"redis {r['redis_prologue']:.3f} shift {r['shift_prologue']:+.3f}")

    v = verdict(rows)
    tag = "EXPLAINED" if v["explained"] else "NOT EXPLAINED"
    print(f"\n== DISCREPANCY: {tag} ==")
    print(f"  {v['why']}")
    if not v["explained"]:
        print("  The paper must withdraw E1's transport row rather than re-label it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
analyze_stall_duration.py
What the measured scheduler counters say, and why they corrected the model.

E-A7 was pre-registered to test one prediction: that measured occupancy `p` -- the fraction of
time the stamping thread is runnable but not running -- falls sharply under SCHED_FIFO, by at
least tenfold, and thereby accounts for the 39-54x fall in the inversion rate that E-A5 measured.

THAT PREDICTION FAILED, and the failure is the useful part. At 75% load the measured occupancy
falls only from 0.557 to 0.319, a factor of 1.75. Nothing like tenfold, and nowhere near enough
to explain a 39x change in inversions. Had `p` remained inferred from the inversion rate, the
model would have agreed with itself and we would never have found this out.

The counters point at stall LENGTH rather than stall FREQUENCY -- but they do not get far enough
to close the argument, and an earlier draft of this file said they did. That draft quoted the
per-process median, which falls 20x at 75% load and 143x at 88%, and concluded that a twentyfold
cut in stall duration explains a fortyfold cut in inversions. Two things are wrong with it.

First, there are two ways to measure stall length and they disagree by an order of magnitude:

    aggregate (total wait / total slices)   0.246 -> 0.076 ms   3.25x     [75% load]
    median across processes                 0.369 -> 0.018 ms  20.0x

A gap that wide means the distribution across processes is heavily skewed -- a few processes
carry most of the waiting -- so the median describes a typical process, not the system, and it
cannot be quoted as though it were the aggregate. On the aggregate the fall is 3-5x. Against a
39-66x fall in the inversion rate, that is NOT sufficient either.

Second, the draft claimed the thread "is scheduled almost as many times". That holds at 75% load
(466k against 464k, ratio 1.00) and fails at 88% (435k against 109k, ratio 3.99).

So the honest position is: occupancy moves about 2x, mean stall length 3-5x, and the inversion
rate moves 40x. NEITHER measured quantity accounts for it.

That is a limit of the instrument rather than an absence of mechanism, and the limit is
structural. schedstat carries cumulative totals, so every quantity derived from it is a MEAN. An
inversion is a TAIL event -- it needs one stall longer than T_true, about 0.5 ms here. A mean
cannot bound a tail. These counters therefore constrain the explanation without resolving it.

What survives is the direction: stall length moves far more than stall frequency does, and
occupancy -- the time-average the model was built on -- is clearly not the variable. That is
still enough to explain why every curve fitted in rho failed, since those were curves in a
time-average of a quantity whose tail is what matters. Resolving it needs the stall DISTRIBUTION,
from sched_switch tracing, which we have not run and which is the next measurement to make.

CLI:
    python scripts/analyze_stall_duration.py --depth docs/results/depth/ea7 \
        --priority docs/results/model/stamping_priority.csv --out docs/results/model
"""
import argparse
import csv
import statistics as st
from collections import defaultdict
from pathlib import Path

OCCUPANCY_PREDICTED = 10.0   # the pre-registered fall in p; recorded so the miss is visible
INVERSION_FALL = 40.0        # the fall in the inversion rate any mechanism here must explain


def load_cell(path):
    """Per-pid deltas over the cell. Processes that never reach the CPU are dropped.

    Under the real-time arm each stamping process has a `sudo chrt` parent, and both match the
    sampler's pattern. The parent blocks on its child, and a blocked task is not runnable, so its
    wait counter never moves -- it contributes exactly zero to both sums. Dropping it on
    on_cpu == 0 is therefore bookkeeping, not a judgement call, and it is verified rather than
    assumed: the caller can check `static` against `active` in the returned summary.
    """
    per = defaultdict(list)
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    per[int(r["pid"])].append((int(r["t_wall_ns"]), int(r["on_cpu_ns"]),
                                               int(r["wait_ns"]), int(r["slices"])))
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError:
        return None
    tot_w = tot_c = tot_s = 0
    means, active, static = [], 0, 0
    for _pid, s in per.items():
        if len(s) < 2:
            continue
        s.sort()
        d_cpu = s[-1][1] - s[0][1]
        d_wait = s[-1][2] - s[0][2]
        d_sl = s[-1][3] - s[0][3]
        if d_cpu <= 0:
            static += 1
            continue
        active += 1
        tot_w += d_wait; tot_c += d_cpu; tot_s += d_sl
        if d_sl > 0:
            means.append(d_wait / d_sl / 1e6)      # ms per scheduling event
    if not active or tot_s <= 0 or (tot_w + tot_c) <= 0:
        return None
    means.sort()
    return {"occupancy": tot_w / (tot_w + tot_c),
            "slices": tot_s,
            "mean_wait_ms": tot_w / tot_s / 1e6,
            "total_wait_s": tot_w / 1e9, "total_cpu_s": tot_c / 1e9,
            "median_wait_ms": st.median(means) if means else float("nan"),
            "p90_wait_ms": means[int(0.9 * (len(means) - 1))] if means else float("nan"),
            "max_wait_ms": max(means) if means else float("nan"),
            "active": active, "static": static}


def load_cells(depth):
    """Every l<pct>_<arm> cell that has a schedstat.csv."""
    out = {}
    for d in sorted(Path(depth).glob("l*_*")):
        if not d.is_dir():
            continue
        level, _, arm = d.name.rpartition("_")
        if arm not in ("base", "rt"):
            continue
        cell = load_cell(d / "schedstat.csv")
        if cell:
            out.setdefault(level, {})[arm] = cell
    return {k: v for k, v in out.items() if set(v) == {"base", "rt"}}


def compare(level, arms):
    b, r = arms["base"], arms["rt"]
    def ratio(x, y):
        return (x / y) if y > 0 else float("inf")
    return {"level": level,
            "occ_base": b["occupancy"], "occ_rt": r["occupancy"],
            "occ_fall": ratio(b["occupancy"], r["occupancy"]),
            "agg_base_ms": b["mean_wait_ms"], "agg_rt_ms": r["mean_wait_ms"],
            "agg_fall": ratio(b["mean_wait_ms"], r["mean_wait_ms"]),
            "med_base_ms": b["median_wait_ms"], "med_rt_ms": r["median_wait_ms"],
            "med_fall": ratio(b["median_wait_ms"], r["median_wait_ms"]),
            "wait_fall": ratio(b["total_wait_s"], r["total_wait_s"]),
            "p90_base_ms": b["p90_wait_ms"], "p90_rt_ms": r["p90_wait_ms"],
            "slices_base": b["slices"], "slices_rt": r["slices"],
            "slice_ratio": ratio(b["slices"], r["slices"])}


def verdict(rows, target_fall=INVERSION_FALL):
    """Which quantity moved, judged on the CONSERVATIVE statistic.

    Two measures of stall length disagree badly, and the disagreement is itself the finding. The
    aggregate mean wait per scheduling event (total wait / total slices) falls 3-5x. The median
    ACROSS PROCESSES of each process's own mean falls 20-143x. A gap that wide means the
    distribution across processes is heavily skewed -- a few processes carry most of the waiting
    -- so the median is not representative of the aggregate and must not be quoted as though it
    were.

    The verdict therefore rests on the aggregate, the number skew cannot inflate, with the median
    reported beside it. On the aggregate, NEITHER occupancy (about 2x) NOR mean stall length
    (3-5x) comes close to accounting for the 39-66x fall in the inversion rate.

    That is a statement about what these counters can see, not an absence of mechanism. schedstat
    carries cumulative totals, so it yields means, and an inversion is a TAIL event: it needs one
    stall longer than T_true. A mean cannot bound a tail.
    """
    if not rows:
        return {"decided": False, "why": "no level has both arms"}
    occ = st.median([r["occ_fall"] for r in rows])
    agg = st.median([r["agg_fall"] for r in rows])
    med = st.median([r["med_fall"] for r in rows])
    sl = st.median([r["slice_ratio"] for r in rows])
    return {"decided": True,
            "occupancy_fall": occ, "aggregate_fall": agg, "median_fall": med,
            "slice_ratio": sl,
            # A median far above the aggregate means skew, not a stronger effect.
            "skewed": med >= 3 * agg,
            "occupancy_prediction_held": occ >= OCCUPANCY_PREDICTED,
            # Conservative: the aggregate must carry at least half the inversion result alone.
            "aggregate_explains": agg >= target_fall / 2,
            "scheduled_as_often": sl < 1.5}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", default="docs/results/depth/ea7")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.depth).is_dir():
        print(f"missing campaign directory: {args.depth}")
        return 1
    cells = load_cells(args.depth)
    if not cells:
        print("no load level has both arms with schedstat data")
        return 1
    rows = [compare(lv, cells[lv]) for lv in sorted(cells)]

    print("== how OFTEN the thread waits (the pre-registered quantity) ==")
    for r in rows:
        print(f"  {r['level']}: occupancy {r['occ_base']:.4f} -> {r['occ_rt']:.4f}"
              f"   fall {r['occ_fall']:.2f}x")
    print("\n== how LONG each wait lasts ==")
    print("   aggregate = total wait / total slices. median = across processes, of each")
    print("   process's own mean. They diverge when a few processes carry the waiting.")
    for r in rows:
        print(f"  {r['level']}: aggregate {r['agg_base_ms']:.4f} -> {r['agg_rt_ms']:.4f} ms"
              f"   fall {r['agg_fall']:.2f}x")
        print(f"       median    {r['med_base_ms']:.4f} -> {r['med_rt_ms']:.4f} ms"
              f"   fall {r['med_fall']:.1f}x     p90 {r['p90_base_ms']:.3f} -> "
              f"{r['p90_rt_ms']:.3f} ms")
    print("\n== how often it is scheduled at all ==")
    for r in rows:
        print(f"  {r['level']}: timeslices {r['slices_base']:,} vs {r['slices_rt']:,}"
              f"   ratio {r['slice_ratio']:.2f}")

    v = verdict(rows)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
    else:
        print(f"the inversion rate falls about {INVERSION_FALL:.0f}x (E-A5, E-A5b).")
        print(f"  occupancy               {v['occupancy_fall']:.2f}x   "
              f"(pre-registered >= {OCCUPANCY_PREDICTED:.0f}x -> "
              f"{'HELD' if v['occupancy_prediction_held'] else 'FAILED'})")
        print(f"  stall length, aggregate {v['aggregate_fall']:.2f}x   "
              f"-> {'sufficient' if v['aggregate_explains'] else 'NOT sufficient'}")
        print(f"  stall length, median    {v['median_fall']:.1f}x"
              + ("   SKEWED: not representative of the aggregate" if v["skewed"] else ""))
        if not v["scheduled_as_often"]:
            print(f"  NOTE: under real-time priority the thread is also scheduled "
                  f"{v['slice_ratio']:.2f}x LESS often,")
            print("        so 'it waits as often, just more briefly' does not hold at "
                  "every level.")
        if v["occupancy_prediction_held"]:
            print("\nThe pre-registered occupancy prediction held.")
        elif v["aggregate_explains"]:
            print("\nOccupancy failed and stall length carries the result on the conservative")
            print("statistic: an inversion needs one stall longer than T_true, not a high")
            print("time-average of waiting.")
        else:
            print("\nNEITHER QUANTITY ACCOUNTS FOR THE RESULT on the conservative statistic.")
            print("  Occupancy moves about 2x and mean stall length 3-5x, against a 40x fall")
            print("  in inversions. The per-process median moves far more, but it is skewed")
            print("  and must not be quoted as if it were the aggregate.")
            print("  This is a limit of the instrument, not an absence of mechanism. schedstat")
            print("  carries cumulative totals, so it yields MEANS, and an inversion is a TAIL")
            print("  event -- one stall beyond T_true. A mean cannot bound a tail. These")
            print("  counters constrain the explanation without resolving it; resolving it")
            print("  needs the stall DISTRIBUTION, from sched_switch tracing, not yet run.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "stall_duration.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

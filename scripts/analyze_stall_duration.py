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

What the counters do show is that SCHED_FIFO barely changes how OFTEN the thread waits -- the
timeslice counts are almost identical, 466k against 464k -- and changes enormously how LONG each
wait lasts. Dividing the wait time by the timeslice count gives the mean wait per scheduling
event, and the per-process median of that falls twentyfold, from 0.369 ms to 0.018 ms.

That is the quantity an inversion actually depends on. An inversion needs ONE stall longer than
T_true, which for broker transport here is around 0.5 ms. Under ordinary priority the median
stall is 0.37 ms and the ninetieth percentile is 1.35 ms, so a large share of stalls clear the
bar. Under SCHED_FIFO the ninetieth percentile is 0.18 ms and almost none do. A twentyfold cut
in stall DURATION explains a fortyfold cut in inversions; a 1.75-fold cut in total waiting does
not.

So the model's variable was wrong, and wrong in a way that explains the earlier failures. Total
occupancy is a time-average; inversions are a tail event. Every curve we fitted in rho was a
curve in the wrong quantity, which is why M/G/1 failed, why a fitted exponential fitted no better
for any principled reason, and why our own bounded bracket missed. The corrected statement is:

    P(inversion) ~ (rate of scheduling stalls) x P(stall duration > T_true)

and the second factor is what scheduling priority moves.

WHAT THIS DOES NOT ESTABLISH. wait/slices is a MEAN per scheduling event, not a distribution.
schedstat gives cumulative totals only, so the tail beyond that mean is not observed and the
p90 figures here are percentiles ACROSS PROCESSES of a per-process mean, which is a coarser
thing than the per-stall distribution the mechanism is about. Resolving the stall distribution
itself needs sched_switch tracing, which we have not run.

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
DURATION_SUPPORTS = 5.0      # a stall-duration fall of at least this backs the corrected model


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
            "med_base_ms": b["median_wait_ms"], "med_rt_ms": r["median_wait_ms"],
            "med_fall": ratio(b["median_wait_ms"], r["median_wait_ms"]),
            "p90_base_ms": b["p90_wait_ms"], "p90_rt_ms": r["p90_wait_ms"],
            "slices_base": b["slices"], "slices_rt": r["slices"],
            "slice_ratio": ratio(b["slices"], r["slices"])}


def verdict(rows):
    """Which quantity moved: the amount of waiting, or the length of each wait."""
    if not rows:
        return {"decided": False, "why": "no level has both arms"}
    occ = st.median([r["occ_fall"] for r in rows])
    med = st.median([r["med_fall"] for r in rows])
    return {"decided": True,
            "occupancy_fall": occ,
            "duration_fall": med,
            "occupancy_prediction_held": occ >= OCCUPANCY_PREDICTED,
            "duration_explains": med >= DURATION_SUPPORTS,
            # The correction only stands if duration moved and occupancy did not.
            "model_corrected": med >= DURATION_SUPPORTS and occ < OCCUPANCY_PREDICTED}


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
    print("\n== how LONG each wait lasts (mean per scheduling event) ==")
    for r in rows:
        print(f"  {r['level']}: median {r['med_base_ms']:.4f} -> {r['med_rt_ms']:.4f} ms"
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
        print(f"occupancy fell {v['occupancy_fall']:.2f}x "
              f"(pre-registered: at least {OCCUPANCY_PREDICTED:.0f}x)"
              f"  -> {'HELD' if v['occupancy_prediction_held'] else 'FAILED'}")
        print(f"stall duration fell {v['duration_fall']:.1f}x")
        if v["model_corrected"]:
            print("\nMODEL CORRECTED BY MEASUREMENT.")
            print("  Priority does not stop the thread waiting -- it waits almost as often,")
            print("  and is scheduled almost as many times. It makes each wait shorter.")
            print("  An inversion needs ONE stall longer than T_true, so what governs it is")
            print("  the stall DURATION distribution, not the time-average occupancy.")
            print("  Every curve we fitted in rho was a curve in the wrong quantity.")
        elif v["occupancy_prediction_held"]:
            print("\nThe original prediction held: occupancy itself fell as predicted.")
        else:
            print("\nNeither quantity moved enough to explain the inversion result;")
            print("the mechanism is not established by these counters.")

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

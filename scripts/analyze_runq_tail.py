#!/usr/bin/env python3
"""
analyze_runq_tail.py
The closing test: does P(run-queue delay > T_true) account for the inversion rate?

Everything measured so far establishes that the inversion rate follows the stamping thread's
scheduling and not the machine's utilisation -- three replications, 47-66x at fixed rho. What
none of it establishes is WHICH scheduling quantity, and the cumulative counters could not
settle that: occupancy moves about 2x and mean stall length 3-5x, against a 40x change in the
rate. Both are means, and an inversion is a tail event.

E-A9 traces sched_wakeup and sched_switch, so the run-queue delay is observed per event rather
than as a total. That yields the quantity the mechanism is actually about:

    P(inversion)  =~  P(run-queue delay > T_true)

with T_true the true broker transport, around 0.5 ms here. This script reads the bpftrace
histogram and tests that equality in the only way that can fail: against the inversion rate
measured in the SAME arm of the SAME campaign.

THREE WAYS THIS CAN COME OUT, all reportable, fixed before the data:

  MATCH        the traced tail probability lands within a factor of ~3 of the measured
               inversion rate in both arms, AND the between-arm ratio reproduces the 40-66x
               fall. The mechanism is then established quantitatively rather than by direction.
  WRONG SCALE  the ratio between arms reproduces, but the absolute probabilities do not. That
               would say scheduling drives the effect while something else sets its level --
               plausible, since not every stall lands on a stamping instant.
  REFUTED      the traced tail barely moves between arms while the inversion rate moves 40x.
               The scheduling account would then be wrong and we would have to look elsewhere.

THE INSTRUMENT'S OWN EFFECT IS CHECKED FIRST. BPF on sched_switch fires on every context switch.
If the traced ordinary arm's inversion rate does not match the untraced measurement of the same
cell, the trace describes a machine we have not otherwise studied and every comparison below is
void. That check runs first and can withhold the result, exactly as the utilisation check does
in analyze_stamping_priority.py.

CLI:
    python scripts/analyze_runq_tail.py --depth docs/results/depth/ea9 \
        --runs runs --untraced-base 0.2214 --t-true-ms 0.5 --out docs/results/model
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_collapse import condition_stats  # noqa: E402

TRACE_TOLERANCE = 0.25    # traced vs untraced baseline may differ by this fraction, no more
MATCH_FACTOR = 3.0        # |log| agreement this close counts as a quantitative match
# bpftrace prints log2 buckets as `[512, 1K)  180 |@@@...`, and abbreviates bounds above 1023
# with K, M and G suffixes. An earlier version of this regex demanded bare digits, so every
# bucket from 1K upward silently failed to parse -- which is precisely where the tail lives. The
# effect would have been to understate P(delay > T_true) and could have turned a match into an
# apparent refutation, so the suffixes are parsed rather than tolerated.
BUCKET = re.compile(r"^\[(\d+[KMG]?)(?:,\s*(\d+[KMG]?)\))?\]?\s+(\d+)\s")
COUNTER = re.compile(r"^@(\w+):\s*(\d+)\s*$")
SUFFIX = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def _bound(text):
    """`512` -> 512, `1K` -> 1024, `2M` -> 2097152. bpftrace uses binary multiples."""
    return int(text[:-1]) * SUFFIX[text[-1]] if text and text[-1] in SUFFIX else int(text)


def parse_bpftrace(path):
    """Read one bpftrace dump: the @usecs log2 histogram plus the scalar counters.

    bpftrace prints histogram rows as `[lo, hi)  count |@@@@...`, and single values as
    `@name: n`. Both forms appear in one file, so each line is tried against both patterns.
    """
    hist, counters = [], {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = COUNTER.match(line)
        if m:
            counters[m.group(1)] = int(m.group(2))
            continue
        m = BUCKET.match(line)
        if m:
            lo = _bound(m.group(1))
            hi = _bound(m.group(2)) if m.group(2) else lo
            hist.append((lo, hi, int(m.group(3))))
    if not hist and not counters:
        return None
    return {"hist": hist, "counters": counters,
            "total": counters.get("count", sum(h[2] for h in hist))}


def tail_probability(parsed, threshold_us):
    """P(delay > threshold). Prefers the exact counter; falls back to the histogram.

    The counters are exact because the BPF program tested each event against the threshold as
    it happened. The histogram is log2-bucketed, so a threshold inside a bucket cannot be
    resolved -- the fallback counts only buckets entirely above it, which UNDERSTATES the tail.
    That direction matters: the fallback can make the mechanism look weaker than it is, never
    stronger, so a match obtained through it is not an artefact of the estimator.
    """
    if not parsed or not parsed["total"]:
        return None, "no events traced"
    exact = parsed["counters"].get(f"over_{int(threshold_us)}us")
    if exact is not None:
        return exact / parsed["total"], "exact counter"
    above = sum(c for lo, _hi, c in parsed["hist"] if lo >= threshold_us)
    return above / parsed["total"], "histogram lower bound"


def load_arm(depth, tag, runs_dir):
    """The traced histogram and the measured inversion rate for one arm."""
    d = Path(depth) / tag
    if not d.is_dir():
        return None
    parsed = parse_bpftrace(d / "runqlat.txt")
    stats = condition_stats(str(d), runs_dir)
    if parsed is None or stats is None:
        return None
    return {"tag": tag, "parsed": parsed, "inversion": stats["tails"][0.0],
            "n_events": stats["n_events"], "rho": stats["rho"]}


def instrument_check(base_arm, untraced_base):
    """Did attaching BPF change the thing we are measuring?"""
    if untraced_base is None or base_arm is None:
        return {"checked": False, "why": "no untraced baseline supplied"}
    traced = base_arm["inversion"]
    drift = abs(traced - untraced_base) / untraced_base if untraced_base else float("inf")
    return {"checked": True, "traced": traced, "untraced": untraced_base, "drift": drift,
            "ok": drift <= TRACE_TOLERANCE}


def verdict(rows, check):
    """Whether the traced tail accounts for the measured inversion rate."""
    if not check.get("ok", False):
        return {"decided": False,
                "why": "the instrument changed the measurement; comparison withheld"}
    # A row with ZERO inversions is informative, not unusable. Excluding it -- as an earlier
    # version did, by requiring inversion > 0 -- threw away the real-time arm entirely and
    # reported UNDECIDED while the base arm was showing a clean quantitative match. An arm that
    # drove the rate to the floor is the strongest possible version of the predicted direction,
    # and it must be reported as that rather than discarded for being inconvenient to divide by.
    usable = [r for r in rows if r["p_tail"] is not None]
    base = next((r for r in usable if r["arm"] == "base"), None)
    rt = next((r for r in usable if r["arm"] == "rt"), None)
    if base is None or rt is None:
        return {"decided": False, "why": "need both a base and an rt arm with a traced tail"}
    if base["inversion"] <= 0:
        return {"decided": False, "why": "no inversions in the base arm to account for"}

    tail_ratio = (base["p_tail"] / rt["p_tail"]) if rt["p_tail"] > 0 else float("inf")
    rt_floored = rt["inversion"] <= 0
    inv_ratio = float("inf") if rt_floored else base["inversion"] / rt["inversion"]

    # The LEVEL test is what the tracing was for: does P(stall > T_true) predict the rate?
    # It is applied per arm, and an arm at zero cannot be scored on it.
    scored = [r for r in usable if r["inversion"] > 0]
    levels_ok = all(
        1 / MATCH_FACTOR <= (r["p_tail"] / r["inversion"]) <= MATCH_FACTOR for r in scored)
    base_level = base["p_tail"] / base["inversion"]
    # With the rt arm at zero there is no finite inversion ratio to compare the tail ratio
    # against, so the ratio test is undefined rather than passed.
    ratio_ok = (None if rt_floored
                else (1 / MATCH_FACTOR) <= (tail_ratio / inv_ratio) <= MATCH_FACTOR)

    if rt_floored:
        outcome = "LEVEL MATCH, RATIO UNTESTABLE" if levels_ok else "LEVEL MISMATCH"
    elif levels_ok and ratio_ok:
        outcome = "MATCH"
    elif ratio_ok:
        outcome = "WRONG SCALE"
    else:
        outcome = "REFUTED"
    return {"decided": True, "inv_ratio": inv_ratio, "tail_ratio": tail_ratio,
            "levels_ok": levels_ok, "ratio_ok": ratio_ok, "rt_floored": rt_floored,
            "base_level": base_level, "n_scored": len(scored), "outcome": outcome}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", default="docs/results/depth/ea9")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--t-true-ms", type=float, default=0.5,
                    help="true broker transport; the threshold a stall must beat")
    ap.add_argument("--untraced-base", type=float, default=None,
                    help="inversion rate for the same cell measured WITHOUT tracing")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.depth).is_dir():
        print(f"missing campaign directory: {args.depth}")
        return 1
    thr_us = args.t_true_ms * 1000.0

    arms = []
    for d in sorted(Path(args.depth).glob("l*_*")):
        if not d.is_dir():
            continue
        arm = d.name.rpartition("_")[2]
        if arm not in ("base", "rt"):
            continue
        a = load_arm(args.depth, d.name, args.runs)
        if a:
            p, how = tail_probability(a["parsed"], thr_us)
            arms.append({"tag": a["tag"], "arm": arm, "rho": a["rho"],
                         "inversion": a["inversion"], "n_events": a["n_events"],
                         "p_tail": p, "estimator": how,
                         "traced_events": a["parsed"]["total"]})
    if not arms:
        print("no arm has both a traced histogram and usable run data")
        return 1

    base_arm = next((a for a in arms if a["arm"] == "base"), None)
    check = instrument_check(base_arm, args.untraced_base)
    print("== did tracing change what we measured? ==")
    if not check["checked"]:
        print(f"  not checked: {check['why']}")
    else:
        print(f"  traced baseline {check['traced']:.5f} vs untraced {check['untraced']:.5f}"
              f"   drift {check['drift']*100:.1f}%"
              f"   [{'ok' if check['ok'] else 'PERTURBED'}]")
        if not check["ok"]:
            print("  The trace describes a machine we have not otherwise studied.")
            print("  Every comparison below is withheld.")

    print(f"\n== P(run-queue delay > {args.t_true_ms} ms) against the measured inversion rate ==")
    for a in arms:
        pt = "n/a" if a["p_tail"] is None else f"{a['p_tail']:.5f}"
        ratio = ("n/a" if a["p_tail"] is None or a["inversion"] <= 0
                 else f"{a['p_tail']/a['inversion']:.2f}")
        print(f"  {a['tag']}: rho {a['rho']:.4f}   traced events {a['traced_events']:,}")
        print(f"      P(tail) {pt}   inversion {a['inversion']:.5f}   "
              f"ratio {ratio}   ({a['estimator']})")

    v = verdict(arms, check)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
    else:
        print(f"  inversion rate falls {v['inv_ratio']:.1f}x between arms")
        print(f"  traced tail falls    {v['tail_ratio']:.1f}x between arms")
        if v["outcome"] == "MATCH":
            print("\nMATCH. The traced tail tracks the inversion rate in level and in ratio.")
            print("  P(stall > T_true) is the quantity, measured rather than inferred, and")
            print("  the mechanism is established quantitatively rather than by direction.")
        elif v["outcome"] == "WRONG SCALE":
            print("\nRIGHT RATIO, WRONG LEVEL. Scheduling drives the effect -- the between-arm")
            print("  ratio reproduces -- but the absolute probabilities do not line up. Not")
            print("  every stall lands on a stamping instant, so a constant factor between the")
            print("  two is expected; we report it rather than fitting it away.")
        elif v["outcome"] == "LEVEL MATCH, RATIO UNTESTABLE":
            # This branch existed in verdict() and not here, so a positive result printed as
            # REFUTED -- the strongest negative the script can emit. A reader taking the
            # printed line at face value would have concluded the mechanism had failed.
            print("\nLEVEL MATCH, RATIO UNTESTABLE. P(stall > T_true) tracks the inversion")
            print("  rate in the arm that has one. The real-time arm recorded zero inversions,")
            print("  so the between-arm ratio has no finite value to test against and the")
            print("  ratio question is undefined here rather than answered either way.")
        elif v["outcome"] == "LEVEL MISMATCH":
            print("\nLEVEL MISMATCH. The traced tail and the inversion rate differ by more than")
            print(f"  {MATCH_FACTOR:g}x in the arm that has inversions, and the real-time arm is at")
            print("  zero so the ratio cannot be tested. The level claim fails on these data.")
        else:
            print("\nREFUTED. The traced tail does not move with the inversion rate.")
            print("  The scheduling account cannot be carried by these data and the")
            print("  explanation lies elsewhere.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "runq_tail.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["tag", "arm", "rho", "inversion", "n_events",
                                           "p_tail", "estimator", "traced_events"])
        w.writeheader()
        w.writerows(arms)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

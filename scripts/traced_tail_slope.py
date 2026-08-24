#!/usr/bin/env python3
"""
traced_tail_slope.py
The referee's second leg: what slope does the traced stall distribution itself have?

Equation 6 fits the inversion rate across the payload sweep as a power law in T_true with
exponent alpha ~= 0.34, and the paper leaned on that exponent for a strong distributional
claim. Referee point M4 (TPDS round 1) asked for the direct check: the E-A9 bpftrace
campaign recorded the full log2 histogram of per-wakeup run-queue delay, so the traced
distribution's own log-log slope is computable with no fitting between campaigns.

What the histogram shows, and what this script therefore reports rather than hides: the
traced survival curve is NOT scale-free. Its local log-log slope is shallow (~0.2-0.3)
through the co-located decade (0.25-2 ms) and steepens sharply beyond 4 ms (>2 by
4-16 ms). Two consequences, both now stated in the manuscript:

  (1) alpha = 0.34 is an EFFECTIVE exponent of the payload span, not a constant of the
      machine's stall distribution -- the infinite-moment reading is withdrawn for the
      measured-range statement (referee M4c);
  (2) the steepening explains, in direction and roughly in size, why Equation 6
      over-predicts the traced tail level at the base payload (the 1.66x of Section 8.3):
      a power law calibrated across the span must sit above a curve that steepens.

One further honesty note, printed with the output: the model's S(t) is the survival of the
RESIDUAL stall seen by an event arriving during a stall, while the histogram records
per-wakeup delay; for heavy tails the residual is one power heavier (length-biasing), so
the two slopes are related, not identical. The comparison is a consistency check, not an
identity, and the manuscript says so.

CLI:
    python scripts/traced_tail_slope.py \
        --runqlat docs/results/depth/ea9/l88_base/runqlat.txt \
        --out docs/results/model/traced_tail_slope.csv
"""
import argparse
import csv
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_runq_tail import BUCKET  # noqa: E402  (the suffix-aware bucket parser)

# OLS windows reported beside the per-boundary local slopes. The first covers the
# co-located decade the closing-loop comparison uses; the last covers the far tail.
WINDOWS_US = ((256, 2048), (512, 4096), (1024, 8192), (4096, 32768))


def _bound_us(token):
    """Turn a bpftrace bucket bound ('512', '1K', '32K') into an integer of microseconds."""
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    if token[-1] in mult:
        return int(token[:-1]) * mult[token[-1]]
    return int(token)


def parse_histogram(lines):
    """Return [(lo_us, count), ...] for the @usecs log2 histogram in a runqlat capture."""
    out = []
    in_hist = False
    for line in lines:
        if line.startswith("@usecs"):
            in_hist = True
            continue
        if not in_hist:
            continue
        m = BUCKET.match(line.strip())
        if not m:
            if out:
                break
            continue
        out.append((_bound_us(m.group(1)), int(m.group(3))))
    return out


def survival(buckets):
    """[(boundary_us, P[delay >= boundary], n_events_at_or_above), ...] per bound."""
    total = sum(c for _, c in buckets)
    rows, remaining = [], total
    for lo, count in buckets:
        rows.append((lo, remaining / total, remaining))
        remaining -= count
    return rows


def local_slopes(surv):
    """Two-point log-log slope between adjacent boundaries, attached to the lower one."""
    out = []
    for (t0, s0, n0), (t1, s1, _) in zip(surv, surv[1:]):
        if s0 <= 0 or s1 <= 0 or t0 <= 0:
            out.append((t0, s0, n0, None))
            continue
        slope = -(math.log(s1) - math.log(s0)) / (math.log(t1) - math.log(t0))
        out.append((t0, s0, n0, round(slope, 3)))
    out.append((surv[-1][0], surv[-1][1], surv[-1][2], None))
    return out


def window_slope(surv, lo_us, hi_us):
    """OLS log-log slope over the boundaries lying inside [lo_us, hi_us], as a
    positive index; None with fewer than three usable points."""
    pts = [(math.log(t), math.log(s)) for t, s, _ in surv
           if lo_us <= t <= hi_us and s > 0]
    if len(pts) < 3:
        return None
    xm = sum(x for x, _ in pts) / len(pts)
    ym = sum(y for _, y in pts) / len(pts)
    num = sum((x - xm) * (y - ym) for x, y in pts)
    den = sum((x - xm) ** 2 for x, _ in pts)
    return round(-num / den, 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--runqlat", default="docs/results/depth/ea9/l88_base/runqlat.txt")
    ap.add_argument("--out", default="docs/results/model/traced_tail_slope.csv")
    args = ap.parse_args(argv)

    lines = Path(args.runqlat).read_text(encoding="utf-8").splitlines()
    buckets = parse_histogram(lines)
    if len(buckets) < 4:
        print(f"FATAL: no usable @usecs histogram in {args.runqlat}")
        return 2

    surv = survival(buckets)
    total = sum(c for _, c in buckets)
    rows = [{"kind": "boundary", "lo_us": t, "hi_us": "", "n_events": n,
             "survival": round(s, 6), "index": sl}
            for t, s, n, sl in local_slopes(surv)]
    for lo, hi in WINDOWS_US:
        rows.append({"kind": "window", "lo_us": lo, "hi_us": hi, "n_events": total,
                     "survival": "", "index": window_slope(surv, lo, hi)})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "lo_us", "hi_us", "n_events",
                                          "survival", "index"])
        w.writeheader()
        w.writerows(rows)

    shallow = window_slope(surv, 256, 2048)
    steep = window_slope(surv, 4096, 32768)
    s512 = {t: sv for t, sv, _ in surv}
    print(f"survival at 512 us: {s512[512]:.4f}" if 512 in s512 else "")
    print(f"windowed index 0.25-2 ms: {shallow} | 4-32 ms: {steep}")
    print("note: per-wakeup delay, not the residual the model's S(t) denotes; the "
          "residual of a heavy-tailed stall process is one power heavier (length bias)")
    if shallow is not None and steep is not None and steep < shallow:
        print("FATAL: the far tail is shallower than the core-adjacent decade; the "
              "manuscript's steepening statement would be false")
        return 1
    print(f"OK: wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
